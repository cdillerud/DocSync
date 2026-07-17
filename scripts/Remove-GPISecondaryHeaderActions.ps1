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
$BackupRoot = Join-Path $RepoRoot ".secondary-action-backup-$Stamp"

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

$TargetActionNames = @(
    "GPIViewDeliveryLog",
    "GPIViewRoutingRules",
    "GPIViewNativeSentEmails"
)

$TargetCaptionPattern = "(?im)^\s*Caption\s*=\s*'Gamer\s+(Document\s+Delivery\s+Log|Document\s+Routing\s+Rules|Sent\s+Email\s+History)'\s*;"

$ModifiedFiles = [System.Collections.Generic.List[string]]::new()
$ModifiedActions = [System.Collections.Generic.List[string]]::new()

foreach ($PageFile in (
    Get-ChildItem -LiteralPath $PageExtRoot -File -Filter "*.al" |
        Sort-Object FullName
)) {
    $Original = Get-Content -LiteralPath $PageFile.FullName -Raw

    if ($Original -notmatch '(?im)^\s*actions\s*\{') {
        continue
    }

    $Updated = $Original
    $ActionPattern = [regex]::new(
        '(?im)^(?<indent>\s*)action\s*\(\s*(?<name>GPI[A-Za-z0-9_]+)\s*\)\s*\{'
    )
    $ActionMatches = @($ActionPattern.Matches($Updated))
    $FileChanged = $false

    for ($MatchIndex = $ActionMatches.Count - 1; $MatchIndex -ge 0; $MatchIndex--) {
        $Match = $ActionMatches[$MatchIndex]
        $ActionName = $Match.Groups["name"].Value
        $OpenBrace = $Updated.IndexOf('{', $Match.Index)
        $CloseBrace = Get-MatchingBraceIndex -Text $Updated -OpenBraceIndex $OpenBrace
        $BlockLength = $CloseBrace - $Match.Index + 1
        $ActionBlock = $Updated.Substring($Match.Index, $BlockLength)

        $IsTarget = ($TargetActionNames -contains $ActionName) -or
            ($ActionBlock -match $TargetCaptionPattern)

        if (-not $IsTarget) {
            continue
        }

        $NewBlock = $ActionBlock

        foreach ($PropertyName in @(
            "Promoted",
            "PromotedCategory",
            "PromotedIsBig",
            "PromotedOnly"
        )) {
            $PropertyPattern = "(?im)^\s*$PropertyName\s*=\s*[^;]+;\s*\r?\n?"
            $NewBlock = [regex]::Replace($NewBlock, $PropertyPattern, "")
        }

        if ($NewBlock -eq $ActionBlock) {
            continue
        }

        $Updated = $Updated.Remove($Match.Index, $BlockLength)
        $Updated = $Updated.Insert($Match.Index, $NewBlock)
        $FileChanged = $true
        $ModifiedActions.Add("$($PageFile.Name): $ActionName")
    }

    if ($FileChanged) {
        Copy-ToBackup -Path $PageFile.FullName
        Set-Content -LiteralPath $PageFile.FullName -Value $Updated -Encoding utf8
        $ModifiedFiles.Add($PageFile.FullName)
    }
}

if ($ModifiedActions.Count -eq 0) {
    throw "No matching Delivery Log, Routing Rules, or Sent Email History actions were changed."
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
    throw "The test extension dependency on the production extension was not found."
}

$TestApp |
    ConvertTo-Json -Depth 50 -Compress |
    Set-Content -LiteralPath $TestAppJson -Encoding utf8

$ExistingChangeLog = Get-Content -LiteralPath $ChangeLog -Raw
$NewEntry = @"
## $NewProdVersion

### Changed
- Kept Gamer Document Delivery Log, Gamer Document Routing Rules, and Gamer Sent Email History inside the Gamer Documents submenu.
- Removed those secondary administration/history actions from the page header action bar.
- Left Gamer email and preview actions promoted for one-click access.

### Safety
- No RDLC or report layout files were changed.
- No document-generation, routing, delivery, archive, or SharePoint behavior was changed.

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
Write-Host " GPI Secondary Header Actions Removed"
Write-Host "============================================================"
Write-Host ""
Write-Host "Updated actions: $($ModifiedActions.Count)"

foreach ($ModifiedAction in $ModifiedActions) {
    Write-Host "  $ModifiedAction"
}

Write-Host ""
Write-Host "Production version: $OldProdVersion -> $NewProdVersion"
Write-Host "Test version:       $OldTestVersion -> $NewTestVersion"
Write-Host "Backup folder:      $BackupRoot"
Write-Host ""
Write-Host "Email and preview actions remain promoted."
Write-Host "Delivery Log, Routing Rules, and Sent Email History remain in Gamer Documents."
Write-Host "No RDLC files were touched."
