[CmdletBinding()]
param(
    [Parameter()]
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"
$ProdAppJson = Join-Path $ProdRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLog = Join-Path $ProdRoot "CHANGELOG.md"

$BoyerDependency = [ordered]@{
    id        = "65994cd5-4d6f-497e-abc0-767b8c392608"
    name      = "Boyer And Associates Custom Package"
    publisher = "Boyer And Associates"
    version   = "25.0.0.10"
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".boyer-dependency-backup-$Stamp"

foreach ($RequiredPath in @($ProdAppJson, $TestAppJson, $ChangeLog)) {
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

Copy-ToBackup -Path $ProdAppJson
Copy-ToBackup -Path $TestAppJson
Copy-ToBackup -Path $ChangeLog

$ProdApp = Get-Content -LiteralPath $ProdAppJson -Raw | ConvertFrom-Json
$OldProdVersion = [string]$ProdApp.version

$Dependencies = @()
if ($null -ne $ProdApp.dependencies) {
    $Dependencies = @($ProdApp.dependencies)
}

$ExistingBoyer = @(
    $Dependencies |
        Where-Object {
            [string]$_.id -eq $BoyerDependency.id
        }
)

if ($ExistingBoyer.Count -gt 1) {
    throw "More than one Boyer dependency already exists in the production app.json."
}

if ($ExistingBoyer.Count -eq 1) {
    $ExistingBoyer[0].name = $BoyerDependency.name
    $ExistingBoyer[0].publisher = $BoyerDependency.publisher
    $ExistingBoyer[0].version = $BoyerDependency.version
    $DependencyAction = "Updated existing dependency"
}
else {
    $Dependencies += [pscustomobject]$BoyerDependency
    $ProdApp.dependencies = @($Dependencies)
    $DependencyAction = "Added dependency"
}

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
- Added the Boyer And Associates Custom Package as an explicit dependency so the Sales Order Documents Sent FactBox can be referenced safely.
- Prepared the extension to place the GPI Documents drag-and-drop FactBox relative to the Boyer Sales Order FactBox after symbols are downloaded.

### Dependency
- App ID: 65994cd5-4d6f-497e-abc0-767b8c392608
- Name: Boyer And Associates Custom Package
- Publisher: Boyer And Associates
- Version: 25.0.0.10

### Safety
- No RDLC or report layout files were changed.
- No page placement was changed by this script.
- No upload, routing, delivery, archive, or SharePoint behavior was changed.

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
Write-Host " Boyer dependency configured"
Write-Host "============================================================"
Write-Host ""
Write-Host "$DependencyAction:"
Write-Host "  App ID:    $($BoyerDependency.id)"
Write-Host "  Name:      $($BoyerDependency.name)"
Write-Host "  Publisher: $($BoyerDependency.publisher)"
Write-Host "  Version:   $($BoyerDependency.version)"
Write-Host ""
Write-Host "Production version: $OldProdVersion -> $NewProdVersion"
Write-Host "Test version:       $OldTestVersion -> $NewTestVersion"
Write-Host "Backup folder:      $BackupRoot"
Write-Host ""
Write-Host "Next step in the production AL project:"
Write-Host "  Run AL: Download Symbols against Sandbox_NoZetadocs_UAT"
Write-Host ""
Write-Host "No page placement was changed."
Write-Host "No RDLC files were touched."
