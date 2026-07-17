[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"
$PageExtRoot = Join-Path $ProdRoot "src\pageextension"
$ProdAppJson = Join-Path $ProdRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLog = Join-Path $ProdRoot "CHANGELOG.md"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".action-layout-backup-$Stamp"

foreach ($RequiredPath in @(
    $PageExtRoot,
    $ProdAppJson,
    $TestAppJson,
    $ChangeLog
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path was not found: $RequiredPath"
    }
}

New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

function Copy-ToBackup {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path $BackupRoot $RelativePath
    $BackupDirectory = Split-Path $BackupPath -Parent

    New-Item -ItemType Directory -Path $BackupDirectory -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

function Get-NextFourPartVersion {
    param(
        [Parameter(Mandatory)]
        [string]$Version
    )

    $Parts = $Version -split '\.'
    if ($Parts.Count -ne 4) {
        throw "Version is not a valid four-part version: $Version"
    }

    $Parts[3] = ([int]$Parts[3] + 1).ToString()
    return ($Parts -join '.')
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
            continue
        }

        if ($Char -eq '}') {
            $Depth--
            if ($Depth -eq 0) {
                return $Index
            }
        }
    }

    throw "A matching closing brace could not be found."
}

function Set-ActionPromotedProperties {
    param(
        [Parameter(Mandatory)]
        [string]$ActionBlock,

        [Parameter(Mandatory)]
        [string]$Indent
    )

    $PropertyIndent = $Indent + "    "
    $Updated = $ActionBlock

    if ($Updated -match '(?im)^\s*Promoted\s*=') {
        $Updated = [regex]::Replace(
            $Updated,
            '(?im)^(\s*)Promoted\s*=\s*(true|false)\s*;',
            '${1}Promoted = true;'
        )
    }
    else {
        $Updated = $Updated.Insert(
            $Updated.IndexOf('{') + 1,
            "`r`n$PropertyIndent" + 'Promoted = true;'
        )
    }

    if ($Updated -match '(?im)^\s*PromotedCategory\s*=') {
        $Updated = [regex]::Replace(
            $Updated,
            '(?im)^(\s*)PromotedCategory\s*=\s*[^;]+;',
            '${1}PromotedCategory = Process;'
        )
    }
    else {
        $Updated = $Updated.Insert(
            $Updated.IndexOf('{') + 1,
            "`r`n$PropertyIndent" + 'PromotedCategory = Process;'
        )
    }

    if ($Updated -match '(?im)^\s*PromotedIsBig\s*=') {
        $Updated = [regex]::Replace(
            $Updated,
            '(?im)^(\s*)PromotedIsBig\s*=\s*(true|false)\s*;',
            '${1}PromotedIsBig = true;'
        )
    }
    else {
        $Updated = $Updated.Insert(
            $Updated.IndexOf('{') + 1,
            "`r`n$PropertyIndent" + 'PromotedIsBig = true;'
        )
    }

    return $Updated
}

$ModifiedFiles = [System.Collections.Generic.List[string]]::new()
$PageFiles = @(
    Get-ChildItem -LiteralPath $PageExtRoot -File -Filter "*.al" |
        Sort-Object FullName
)

foreach ($PageFile in $PageFiles) {
    $Original = Get-Content -LiteralPath $PageFile.FullName -Raw

    if ($Original -notmatch '(?im)\b(action|group)\s*\(\s*GPI') {
        continue
    }

    $Updated = $Original

    # Move every insertion block that contains Gamer/GPI actions to the top
    # of the standard Processing action group.
    $InsertionPattern = [regex]::new(
        '(?im)\b(addlast|addfirst|addafter|addbefore)\s*\(\s*([^)]+)\s*\)\s*\{'
    )

    $InsertionMatches = @($InsertionPattern.Matches($Updated))

    for ($MatchIndex = $InsertionMatches.Count - 1; $MatchIndex -ge 0; $MatchIndex--) {
        $Match = $InsertionMatches[$MatchIndex]
        $OpenBraceIndex = $Updated.IndexOf('{', $Match.Index)
        $CloseBraceIndex = Get-MatchingBraceIndex `
            -Text $Updated `
            -OpenBraceIndex $OpenBraceIndex

        $BlockLength = $CloseBraceIndex - $Match.Index + 1
        $Block = $Updated.Substring($Match.Index, $BlockLength)

        if ($Block -notmatch '(?im)\b(action|group)\s*\(\s*GPI') {
            continue
        }

        $HeaderLength = $OpenBraceIndex - $Match.Index
        $CurrentHeader = $Updated.Substring($Match.Index, $HeaderLength)
        $NewHeader = [regex]::Replace(
            $CurrentHeader,
            '(?im)\b(addlast|addfirst|addafter|addbefore)\s*\(\s*([^)]+)\s*\)',
            'addfirst(Processing)'
        )

        $Updated = $Updated.Remove($Match.Index, $HeaderLength)
        $Updated = $Updated.Insert($Match.Index, $NewHeader)
    }

    # Promote every GPI action so it also appears in the page action bar.
    $ActionPattern = [regex]::new(
        '(?im)^(?<indent>\s*)action\s*\(\s*(?<name>GPI[A-Za-z0-9_]+)\s*\)\s*\{'
    )

    $ActionMatches = @($ActionPattern.Matches($Updated))

    for ($MatchIndex = $ActionMatches.Count - 1; $MatchIndex -ge 0; $MatchIndex--) {
        $Match = $ActionMatches[$MatchIndex]
        $OpenBraceIndex = $Updated.IndexOf('{', $Match.Index)
        $CloseBraceIndex = Get-MatchingBraceIndex `
            -Text $Updated `
            -OpenBraceIndex $OpenBraceIndex

        $BlockLength = $CloseBraceIndex - $Match.Index + 1
        $Block = $Updated.Substring($Match.Index, $BlockLength)
        $Indent = $Match.Groups['indent'].Value

        $NewBlock = Set-ActionPromotedProperties `
            -ActionBlock $Block `
            -Indent $Indent

        $Updated = $Updated.Remove($Match.Index, $BlockLength)
        $Updated = $Updated.Insert($Match.Index, $NewBlock)
    }

    if ($Updated -ne $Original) {
        Copy-ToBackup -Path $PageFile.FullName
        Set-Content -LiteralPath $PageFile.FullName -Value $Updated -Encoding utf8
        $ModifiedFiles.Add($PageFile.FullName)
    }
}

if ($ModifiedFiles.Count -eq 0) {
    throw "No page-extension action files were changed. The script stopped before changing versions."
}

Copy-ToBackup -Path $ProdAppJson
Copy-ToBackup -Path $TestAppJson
Copy-ToBackup -Path $ChangeLog

$ProdApp = Get-Content -LiteralPath $ProdAppJson -Raw | ConvertFrom-Json
$OldProdVersion = [string]$ProdApp.version
$NewProdVersion = Get-NextFourPartVersion -Version $OldProdVersion
$ProdApp.version = $NewProdVersion

$ProdApp |
    ConvertTo-Json -Depth 50 -Compress |
    Set-Content -LiteralPath $ProdAppJson -Encoding utf8

$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json
$OldTestVersion = [string]$TestApp.version
$NewTestVersion = Get-NextFourPartVersion -Version $OldTestVersion
$TestApp.version = $NewTestVersion

$DependencyUpdated = $false
foreach ($Dependency in @($TestApp.dependencies)) {
    if ([string]$Dependency.id -eq [string]$ProdApp.id) {
        $Dependency.version = $NewProdVersion
        $DependencyUpdated = $true
    }
}

if (-not $DependencyUpdated) {
    throw "The test extension dependency on the production app was not found."
}

$TestApp |
    ConvertTo-Json -Depth 50 -Compress |
    Set-Content -LiteralPath $TestAppJson -Encoding utf8

$ExistingChangeLog = Get-Content -LiteralPath $ChangeLog -Raw
$NewEntry = @"
## $NewProdVersion

### Changed
- Moved every Gamer/GPI page-action insertion block to the first position in the standard Processing action group.
- Promoted every Gamer/GPI page action to the page action bar using the Process category.
- Standardized action placement across Customer, Vendor, Sales, Purchase, Return, Transfer, and posted-document pages wherever GPI page actions are present.

### Safety
- No report layouts or RDLC files were changed.
- No document-generation, routing, delivery, archive, or SharePoint logic was changed.
- This release changes page-action placement and promotion only.

"@

if ($ExistingChangeLog -match '^# Changelog\s*\r?\n') {
    $UpdatedChangeLog = [regex]::Replace(
        $ExistingChangeLog,
        '^# Changelog\s*\r?\n',
        "# Changelog`r`n`r`n$NewEntry",
        1
    )
}
else {
    $UpdatedChangeLog = "# Changelog`r`n`r`n$NewEntry$ExistingChangeLog"
}

Set-Content -LiteralPath $ChangeLog -Value $UpdatedChangeLog -Encoding utf8

Write-Host ""
Write-Host "============================================================"
Write-Host " GPI Action Layout Consistency Patch"
Write-Host "============================================================"
Write-Host ""
Write-Host "Modified page-extension files: $($ModifiedFiles.Count)"

foreach ($ModifiedFile in $ModifiedFiles) {
    Write-Host "  $ModifiedFile"
}

Write-Host ""
Write-Host "Production version: $OldProdVersion -> $NewProdVersion"
Write-Host "Test version:       $OldTestVersion -> $NewTestVersion"
Write-Host "Backup folder:      $BackupRoot"
Write-Host ""
Write-Host "No RDLC files were touched."
Write-Host ""
Write-Host "Next:"
Write-Host "  1. Run Test-GPIStaticChecks.ps1"
Write-Host "  2. Run Prepare-GPIALTests.ps1"
Write-Host "  3. Publish production first, then tests, to Sandbox_NoZetadocs_UAT"
