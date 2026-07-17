[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"

$RecordDocsFile = Join-Path $ProdRoot "src\pageextension\GPISalesOrderRecordDocuments.PageExt.al"
$ProdAppJson = Join-Path $ProdRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLog = Join-Path $ProdRoot "CHANGELOG.md"

$BoyerAppId = "65994cd5-4d6f-497e-abc0-767b8c392608"
$BoyerAnchorControl = "Page50004"

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".sales-order-documents-placement-backup-$Stamp"

foreach ($RequiredPath in @(
    $RecordDocsFile,
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

function Write-JsonFile {
    param(
        [Parameter(Mandatory)]
        [object]$Object,

        [Parameter(Mandatory)]
        [string]$Path
    )

    $Json = $Object | ConvertTo-Json -Depth 100
    Set-Content -LiteralPath $Path -Value $Json -Encoding utf8
}

# Confirm the required Boyer dependency exists before referencing its control.
$ProdApp = Get-Content -LiteralPath $ProdAppJson -Raw | ConvertFrom-Json

$BoyerDependencies = @(
    @($ProdApp.dependencies) |
        Where-Object {
            [string]$_.id -eq $BoyerAppId
        }
)

if ($BoyerDependencies.Count -ne 1) {
    throw "Expected exactly one Boyer dependency in production app.json, but found $($BoyerDependencies.Count)."
}

$RecordDocsText = Get-Content -LiteralPath $RecordDocsFile -Raw

$AlreadyPlacedPattern = '(?im)\baddafter\s*\(\s*Page50004\s*\)'
if ($RecordDocsText -match $AlreadyPlacedPattern) {
    Write-Host ""
    Write-Host "The Sales Order Documents FactBox is already placed after Page50004."
    Write-Host "No files were changed."
    exit 0
}

$OldPlacementPattern = '(?im)\baddlast\s*\(\s*FactBoxes\s*\)'
$PlacementMatches = @([regex]::Matches($RecordDocsText, $OldPlacementPattern))

if ($PlacementMatches.Count -ne 1) {
    throw "Expected exactly one addlast(FactBoxes) placement in $RecordDocsFile, but found $($PlacementMatches.Count)."
}

Copy-ToBackup -Path $RecordDocsFile
Copy-ToBackup -Path $ProdAppJson
Copy-ToBackup -Path $TestAppJson
Copy-ToBackup -Path $ChangeLog

$UpdatedRecordDocsText = [regex]::Replace(
    $RecordDocsText,
    $OldPlacementPattern,
    "addafter($BoyerAnchorControl)",
    1
)

Set-Content -LiteralPath $RecordDocsFile -Value $UpdatedRecordDocsText -Encoding utf8

$OldProdVersion = [string]$ProdApp.version
$NewProdVersion = Get-NextFourPartVersion -Version $OldProdVersion
$ProdApp.version = $NewProdVersion
Write-JsonFile -Object $ProdApp -Path $ProdAppJson

$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json
$OldTestVersion = [string]$TestApp.version
$NewTestVersion = Get-NextFourPartVersion -Version $OldTestVersion
$TestApp.version = $NewTestVersion

$ProdDependencyUpdated = $false

foreach ($Dependency in @($TestApp.dependencies)) {
    if ([string]$Dependency.id -eq [string]$ProdApp.id) {
        $Dependency.version = $NewProdVersion
        $ProdDependencyUpdated = $true
    }
}

if (-not $ProdDependencyUpdated) {
    throw "The test extension dependency on the production extension was not found."
}

Write-JsonFile -Object $TestApp -Path $TestAppJson

$ExistingChangeLog = Get-Content -LiteralPath $ChangeLog -Raw

$NewEntry = @"
## $NewProdVersion

### Changed
- Moved the Sales Order Documents drag-and-drop FactBox directly below the Boyer Sales Order Documents Sent FactBox.
- Anchored the GPI Documents FactBox after Boyer control Page50004.
- Kept the existing record-specific SharePoint path, upload, and document-list behavior unchanged.

### Safety
- No RDLC or report layout files were changed.
- No email, routing, delivery, archive, or SharePoint logic was changed.

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
    $UpdatedChangeLog = "$NewEntry`r`n$ExistingChangeLog"
}

Set-Content -LiteralPath $ChangeLog -Value $UpdatedChangeLog -Encoding utf8

Write-Host ""
Write-Host "============================================================"
Write-Host " Sales Order Documents FactBox placement updated"
Write-Host "============================================================"
Write-Host ""
Write-Host "Changed file:"
Write-Host "  $RecordDocsFile"
Write-Host ""
Write-Host "Old placement:"
Write-Host "  addlast(FactBoxes)"
Write-Host ""
Write-Host "New placement:"
Write-Host "  addafter($BoyerAnchorControl)"
Write-Host ""
Write-Host "Production version: $OldProdVersion -> $NewProdVersion"
Write-Host "Test version:       $OldTestVersion -> $NewTestVersion"
Write-Host "Backup folder:      $BackupRoot"
Write-Host ""
Write-Host "No RDLC files were touched."
