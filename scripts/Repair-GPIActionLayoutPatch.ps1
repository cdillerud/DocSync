[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs",

    [Parameter()]
    [string]$BackupRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($BackupRoot)) {
    $BackupRoot = Get-ChildItem -LiteralPath $RepoRoot -Directory -Filter ".action-layout-backup-*" |
        Sort-Object Name -Descending |
        Select-Object -First 1 |
        ForEach-Object FullName
}

if ([string]::IsNullOrWhiteSpace($BackupRoot) -or -not (Test-Path -LiteralPath $BackupRoot)) {
    throw "The action-layout backup folder could not be found."
}

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"
$PageExtRoot = Join-Path $ProdRoot "src\pageextension"
$ProdAppJson = Join-Path $ProdRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLog = Join-Path $ProdRoot "CHANGELOG.md"

Write-Host ""
Write-Host "============================================================"
Write-Host " Repair GPI Action Layout Patch"
Write-Host "============================================================"
Write-Host "Backup source: $BackupRoot"
Write-Host ""

# Restore exactly the files captured immediately before the bad patch.
$BackupFiles = Get-ChildItem -LiteralPath $BackupRoot -File -Recurse
if ($BackupFiles.Count -eq 0) {
    throw "The backup folder contains no files."
}

foreach ($BackupFile in $BackupFiles) {
    $RelativePath = $BackupFile.FullName.Substring($BackupRoot.Length).TrimStart('\')
    $Destination = Join-Path $RepoRoot $RelativePath
    $DestinationFolder = Split-Path $Destination -Parent

    New-Item -ItemType Directory -Path $DestinationFolder -Force | Out-Null
    Copy-Item -LiteralPath $BackupFile.FullName -Destination $Destination -Force
    Write-Host "[RESTORED] $RelativePath"
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

    $Properties = @(
        @{ Name = "Promoted"; Value = "true" },
        @{ Name = "PromotedCategory"; Value = "Process" },
        @{ Name = "PromotedIsBig"; Value = "true" }
    )

    foreach ($Property in $Properties) {
        $Pattern = "(?im)^(\s*)$([regex]::Escape($Property.Name))\s*=\s*[^;]+;"
        if ($Updated -match $Pattern) {
            $Updated = [regex]::Replace(
                $Updated,
                $Pattern,
                '${1}' + $Property.Name + ' = ' + $Property.Value + ';'
            )
        }
        else {
            $InsertAt = $Updated.IndexOf('{') + 1
            $Updated = $Updated.Insert(
                $InsertAt,
                "`r`n$PropertyIndent$($Property.Name) = $($Property.Value);"
            )
        }
    }

    return $Updated
}

function Get-NextVersion {
    param([Parameter(Mandatory)][string]$Version)

    $Parts = $Version -split '\.'
    if ($Parts.Count -ne 4) {
        throw "Unexpected version format: $Version"
    }

    $Parts[3] = ([int]$Parts[3] + 1).ToString()
    return ($Parts -join '.')
}

# Only standard Business Central document/customer/vendor pages are moved to
# addfirst(Processing). Custom GPI pages keep their existing action containers.
$ProcessingTargets = @(
    "Customer Card",
    "Customer List",
    "Vendor Card",
    "Vendor List",
    "Sales Order",
    "Sales Order List",
    "Sales Return Order",
    "Purchase Order",
    "Purchase Order List",
    "Purchase Return Order",
    "Transfer Order",
    "Posted Sales Invoice",
    "Posted Sales Invoices",
    "Posted Sales Credit Memo",
    "Posted Sales Credit Memos",
    "Posted Purchase Invoice",
    "Posted Purchase Invoices",
    "Posted Purchase Credit Memo",
    "Posted Purchase Credit Memos",
    "Sales Credit Memo",
    "Purchase Credit Memo"
)

$ModifiedFiles = [System.Collections.Generic.List[string]]::new()

foreach ($PageFile in (Get-ChildItem -LiteralPath $PageExtRoot -File -Filter "*.al" | Sort-Object FullName)) {
    $Original = Get-Content -LiteralPath $PageFile.FullName -Raw

    if ($Original -notmatch '(?im)^\s*actions\s*\{') {
        continue
    }

    if ($Original -notmatch '(?im)\baction\s*\(\s*GPI') {
        continue
    }

    $TargetPage = ""
    if ($Original -match '(?im)^\s*pageextension\s+\d+\s+"[^"]+"\s+extends\s+"([^"]+)"') {
        $TargetPage = $Matches[1]
    }

    $ActionsMatch = [regex]::Match($Original, '(?im)^\s*actions\s*\{')
    $ActionsOpenBrace = $Original.IndexOf('{', $ActionsMatch.Index)
    $ActionsCloseBrace = Get-MatchingBraceIndex -Text $Original -OpenBraceIndex $ActionsOpenBrace
    $ActionsLength = $ActionsCloseBrace - $ActionsMatch.Index + 1
    $ActionsBlock = $Original.Substring($ActionsMatch.Index, $ActionsLength)
    $UpdatedActions = $ActionsBlock

    # Move only action insertion blocks, never layout insertion blocks.
    if ($ProcessingTargets -contains $TargetPage) {
        $InsertionPattern = [regex]::new(
            '(?im)\b(addlast|addfirst|addafter|addbefore)\s*\(\s*([^)]+)\s*\)\s*\{'
        )

        $InsertionMatches = @($InsertionPattern.Matches($UpdatedActions))

        for ($MatchIndex = $InsertionMatches.Count - 1; $MatchIndex -ge 0; $MatchIndex--) {
            $Match = $InsertionMatches[$MatchIndex]
            $OpenBrace = $UpdatedActions.IndexOf('{', $Match.Index)
            $CloseBrace = Get-MatchingBraceIndex -Text $UpdatedActions -OpenBraceIndex $OpenBrace
            $Block = $UpdatedActions.Substring($Match.Index, $CloseBrace - $Match.Index + 1)

            if ($Block -notmatch '(?im)\b(action|group)\s*\(\s*GPI') {
                continue
            }

            $HeaderLength = $OpenBrace - $Match.Index
            $Header = $UpdatedActions.Substring($Match.Index, $HeaderLength)
            $NewHeader = [regex]::Replace(
                $Header,
                '(?im)\b(addlast|addfirst|addafter|addbefore)\s*\(\s*([^)]+)\s*\)',
                'addfirst(Processing)'
            )

            $UpdatedActions = $UpdatedActions.Remove($Match.Index, $HeaderLength)
            $UpdatedActions = $UpdatedActions.Insert($Match.Index, $NewHeader)
        }
    }

    # Promote every GPI action inside the actions section.
    $ActionPattern = [regex]::new(
        '(?im)^(?<indent>\s*)action\s*\(\s*(?<name>GPI[A-Za-z0-9_]+)\s*\)\s*\{'
    )

    $ActionMatches = @($ActionPattern.Matches($UpdatedActions))

    for ($MatchIndex = $ActionMatches.Count - 1; $MatchIndex -ge 0; $MatchIndex--) {
        $Match = $ActionMatches[$MatchIndex]
        $OpenBrace = $UpdatedActions.IndexOf('{', $Match.Index)
        $CloseBrace = Get-MatchingBraceIndex -Text $UpdatedActions -OpenBraceIndex $OpenBrace
        $BlockLength = $CloseBrace - $Match.Index + 1
        $Block = $UpdatedActions.Substring($Match.Index, $BlockLength)
        $Indent = $Match.Groups['indent'].Value

        $NewBlock = Set-ActionPromotedProperties -ActionBlock $Block -Indent $Indent
        $UpdatedActions = $UpdatedActions.Remove($Match.Index, $BlockLength)
        $UpdatedActions = $UpdatedActions.Insert($Match.Index, $NewBlock)
    }

    if ($UpdatedActions -ne $ActionsBlock) {
        $UpdatedFile = $Original.Remove($ActionsMatch.Index, $ActionsLength)
        $UpdatedFile = $UpdatedFile.Insert($ActionsMatch.Index, $UpdatedActions)
        Set-Content -LiteralPath $PageFile.FullName -Value $UpdatedFile -Encoding utf8
        $ModifiedFiles.Add($PageFile.FullName)
        Write-Host "[PATCHED] $($PageFile.Name) -> $TargetPage"
    }
}

if ($ModifiedFiles.Count -eq 0) {
    throw "No valid page action files were modified."
}

$ProdApp = Get-Content -LiteralPath $ProdAppJson -Raw | ConvertFrom-Json
$OldProdVersion = [string]$ProdApp.version
$NewProdVersion = Get-NextVersion -Version $OldProdVersion
$ProdApp.version = $NewProdVersion
$ProdApp | ConvertTo-Json -Depth 50 -Compress | Set-Content -LiteralPath $ProdAppJson -Encoding utf8

$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json
$OldTestVersion = [string]$TestApp.version
$NewTestVersion = Get-NextVersion -Version $OldTestVersion
$TestApp.version = $NewTestVersion

$DependencyFound = $false
foreach ($Dependency in @($TestApp.dependencies)) {
    if ([string]$Dependency.id -eq [string]$ProdApp.id) {
        $Dependency.version = $NewProdVersion
        $DependencyFound = $true
    }
}

if (-not $DependencyFound) {
    throw "The test extension dependency on the production extension was not found."
}

$TestApp | ConvertTo-Json -Depth 50 -Compress | Set-Content -LiteralPath $TestAppJson -Encoding utf8

$ExistingChangeLog = Get-Content -LiteralPath $ChangeLog -Raw
$NewEntry = @"
## $NewProdVersion

### Changed
- Moved Gamer/GPI actions to the first position in the Processing group on supported standard Business Central pages.
- Promoted Gamer/GPI actions to the page action bar using the Process category.
- Preserved layout-only extensions and custom GPI page containers.

### Safety
- No RDLC or report layout files were changed.
- No document-generation, routing, email, archive, or SharePoint behavior was changed.

"@

$UpdatedChangeLog = [regex]::Replace(
    $ExistingChangeLog,
    '^# Changelog\s*\r?\n',
    "# Changelog`r`n`r`n$NewEntry",
    1
)
Set-Content -LiteralPath $ChangeLog -Value $UpdatedChangeLog -Encoding utf8

Write-Host ""
Write-Host "============================================================"
Write-Host " Repair complete"
Write-Host "============================================================"
Write-Host "Modified page action files: $($ModifiedFiles.Count)"
Write-Host "Production version: $OldProdVersion -> $NewProdVersion"
Write-Host "Test version:       $OldTestVersion -> $NewTestVersion"
Write-Host ""
Write-Host "Layout-only files were restored and left unchanged."
Write-Host "No RDLC files were touched."
