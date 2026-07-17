[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProdPageExtRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement\src\pageextension"
$TestFile = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests\src\codeunit\GPIUATSimulationTests.Codeunit.al"
$TestAppJson = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests\app.json"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

foreach ($RequiredPath in @($ProdPageExtRoot, $TestFile, $TestAppJson)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path not found: $RequiredPath"
    }
}

function Get-MatchingBraceIndex {
    param(
        [Parameter(Mandatory)]
        [string]$Text,

        [Parameter(Mandatory)]
        [int]$OpenBraceIndex
    )

    $Depth = 0
    $InString = $false
    $InLineComment = $false
    $InBlockComment = $false

    for ($Index = $OpenBraceIndex; $Index -lt $Text.Length; $Index++) {
        $Char = $Text[$Index]
        $NextChar = if (($Index + 1) -lt $Text.Length) {
            $Text[$Index + 1]
        }
        else {
            [char]0
        }

        if ($InLineComment) {
            if ($Char -eq "`n") {
                $InLineComment = $false
            }
            continue
        }

        if ($InBlockComment) {
            if ($Char -eq '*' -and $NextChar -eq '/') {
                $InBlockComment = $false
                $Index++
            }
            continue
        }

        if (-not $InString -and $Char -eq '/' -and $NextChar -eq '/') {
            $InLineComment = $true
            $Index++
            continue
        }

        if (-not $InString -and $Char -eq '/' -and $NextChar -eq '*') {
            $InBlockComment = $true
            $Index++
            continue
        }

        if ($Char -eq "'") {
            if ($InString -and $NextChar -eq "'") {
                $Index++
                continue
            }

            $InString = -not $InString
            continue
        }

        if ($InString) {
            continue
        }

        if ($Char -eq '{') {
            $Depth++
        }
        elseif ($Char -eq '}') {
            $Depth--
            if ($Depth -eq 0) {
                return $Index
            }
        }
    }

    throw "Matching closing brace not found."
}

# Discover the actual codeunit and public method used by the Customer Card action.
$ActionSourceFile = $null
$ActionBlock = $null

foreach ($PageFile in (Get-ChildItem -LiteralPath $ProdPageExtRoot -File -Filter "*.al" -Recurse)) {
    $Content = Get-Content -LiteralPath $PageFile.FullName -Raw
    $ActionMatch = [regex]::Match(
        $Content,
        '(?im)^\s*action\s*\(\s*GPIEmailOpenOrderStatus\s*\)\s*\{'
    )

    if (-not $ActionMatch.Success) {
        continue
    }

    if ($ActionSourceFile) {
        throw "More than one GPIEmailOpenOrderStatus action was found."
    }

    $OpenBrace = $Content.IndexOf('{', $ActionMatch.Index)
    $CloseBrace = Get-MatchingBraceIndex -Text $Content -OpenBraceIndex $OpenBrace
    $ActionSourceFile = $PageFile.FullName
    $ActionBlock = $Content.Substring(
        $ActionMatch.Index,
        $CloseBrace - $ActionMatch.Index + 1
    )
}

if (-not $ActionSourceFile -or -not $ActionBlock) {
    throw "Could not find action(GPIEmailOpenOrderStatus) in the production page extensions."
}

$CodeunitDeclarations = @(
    [regex]::Matches(
        $ActionBlock,
        '(?im)^\s*(?<Variable>[A-Za-z_][A-Za-z0-9_]*):\s*Codeunit\s+"(?<Type>[^"]+)"\s*;'
    )
)

$ServiceVariable = $null
$ServiceType = $null
$ServiceMethod = $null
$ServiceArguments = $null

foreach ($Declaration in $CodeunitDeclarations) {
    $CandidateVariable = $Declaration.Groups['Variable'].Value
    $CandidateType = $Declaration.Groups['Type'].Value
    $CallPattern = '(?im)\b' +
        [regex]::Escape($CandidateVariable) +
        '\.(?<Method>[A-Za-z_][A-Za-z0-9_]*)\s*\((?<Arguments>[^;]*)\)\s*;'

    $CallMatch = [regex]::Match($ActionBlock, $CallPattern)
    if (-not $CallMatch.Success) {
        continue
    }

    $ServiceVariable = $CandidateVariable
    $ServiceType = $CandidateType
    $ServiceMethod = $CallMatch.Groups['Method'].Value
    $ServiceArguments = $CallMatch.Groups['Arguments'].Value.Trim()
    break
}

if (-not $ServiceType -or -not $ServiceMethod) {
    throw "Could not determine the codeunit method called by GPIEmailOpenOrderStatus."
}

# Translate the page record reference to the test's Customer variable.
$DirectArguments = [regex]::Replace(
    $ServiceArguments,
    '(?i)\bRec\b',
    'Customer'
)

if ([string]::IsNullOrWhiteSpace($DirectArguments)) {
    throw "The discovered action service call has no argument. The patch stopped without changing the test."
}

$TestContent = Get-Content -LiteralPath $TestFile -Raw
$ProcedureMatch = [regex]::Match(
    $TestContent,
    '(?im)^\s*procedure\s+OpenOrderCardPageActionCreatesIsolatedUATDelivery\s*\(\s*\)\s*'
)

if (-not $ProcedureMatch.Success) {
    throw "The target test procedure was not found."
}

# AL procedure bodies use begin/end rather than braces. Find the next test
# using the instance Match overload that accepts a starting position.
$NextTestRegex = [regex]::new('(?im)^\s*\[Test\]')
$SearchStart = $ProcedureMatch.Index + $ProcedureMatch.Length
$NextTestMatch = $NextTestRegex.Match($TestContent, $SearchStart)

$ProcedureEnd = if ($NextTestMatch.Success) {
    $NextTestMatch.Index
}
else {
    $TestContent.Length
}

$ProcedureBlock = $TestContent.Substring(
    $ProcedureMatch.Index,
    $ProcedureEnd - $ProcedureMatch.Index
)

$CustomerCardDeclarationPattern = '(?im)^(?<Indent>\s*)CustomerCard:\s*TestPage\s+"Customer Card"\s*;\s*$'
$CustomerCardDeclaration = [regex]::Match(
    $ProcedureBlock,
    $CustomerCardDeclarationPattern
)

if (-not $CustomerCardDeclaration.Success) {
    throw "The CustomerCard TestPage declaration was not found in the target test."
}

$DeclarationIndent = $CustomerCardDeclaration.Groups['Indent'].Value
$NewDeclaration = $DeclarationIndent +
    'OpenOrderWorkflow: Codeunit "' +
    $ServiceType +
    '";'

$CustomerCardDeclarationRegex = [regex]::new($CustomerCardDeclarationPattern)
$UpdatedProcedure = $CustomerCardDeclarationRegex.Replace(
    $ProcedureBlock,
    [System.Text.RegularExpressions.MatchEvaluator]{
        param($Match)
        return $NewDeclaration
    },
    1
)

$UiBlockPattern = '(?ims)^\s*BindSubscription\(Mock\);\s*' +
    'CustomerCard\.OpenEdit\(\);\s*' +
    'CustomerCard\.(GoToRecord\(Customer\)|GoToKey\(Customer\."No\."\));\s*' +
    'CustomerCard\.GPIEmailOpenOrderStatus\.Invoke\(\);\s*' +
    'CustomerCard\.Close\(\);\s*' +
    'UnbindSubscription\(Mock\);\s*'

$UiBlockMatch = [regex]::Match($UpdatedProcedure, $UiBlockPattern)
if (-not $UiBlockMatch.Success) {
    throw "The expected Customer Card TestPage execution block was not found."
}

$Replacement = @"
        // Exercise the same public application service used by the Customer Card action.
        // This avoids nondeterministic Microsoft Customer Card camera initialization
        // while retaining report, routing, transport, and Delivery Log validation.
        BindSubscription(Mock);
        Commit();
        OpenOrderWorkflow.$ServiceMethod($DirectArguments);
        UnbindSubscription(Mock);

"@

$UiBlockRegex = [regex]::new($UiBlockPattern)
$UpdatedProcedure = $UiBlockRegex.Replace(
    $UpdatedProcedure,
    [System.Text.RegularExpressions.MatchEvaluator]{
        param($Match)
        return $Replacement
    },
    1
)

$UpdatedTestContent = $TestContent.Remove(
    $ProcedureMatch.Index,
    $ProcedureBlock.Length
)
$UpdatedTestContent = $UpdatedTestContent.Insert(
    $ProcedureMatch.Index,
    $UpdatedProcedure
)

$TestBackup = "$TestFile.$Stamp.bak"
$AppBackup = "$TestAppJson.$Stamp.bak"
Copy-Item -LiteralPath $TestFile -Destination $TestBackup -Force
Copy-Item -LiteralPath $TestAppJson -Destination $AppBackup -Force

Set-Content -LiteralPath $TestFile -Value $UpdatedTestContent -Encoding utf8

$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json
$OldTestVersion = [string]$TestApp.version
$VersionParts = $OldTestVersion -split '\.'

if ($VersionParts.Count -ne 4) {
    throw "Unexpected test extension version format: $OldTestVersion"
}

$VersionParts[3] = ([int]$VersionParts[3] + 1).ToString()
$NewTestVersion = $VersionParts -join '.'
$TestApp.version = $NewTestVersion

$TestApp |
    ConvertTo-Json -Depth 50 -Compress |
    Set-Content -LiteralPath $TestAppJson -Encoding utf8

Write-Host ""
Write-Host "============================================================"
Write-Host " Open Order Card test made deterministic"
Write-Host "============================================================"
Write-Host "Action source:      $ActionSourceFile"
Write-Host "Service codeunit:   $ServiceType"
Write-Host "Service method:     $ServiceMethod"
Write-Host "Service arguments:  $DirectArguments"
Write-Host "Test version:       $OldTestVersion -> $NewTestVersion"
Write-Host ""
Write-Host "Production extension was not changed."
Write-Host "No RDLC files were touched."
Write-Host ""
Write-Host "Backups:"
Write-Host "  $TestBackup"
Write-Host "  $AppBackup"
