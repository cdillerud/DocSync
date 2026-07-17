[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# This restores the layouts from the backup taken BEFORE the first Gamer Contacts stacking attempt.
# That backup is the 0.27.0.11 state.
$RestoredProductionVersion = "0.27.0.15"
$RestoredTestVersion = "0.8.0.15"

$ProductionRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement-tests"
$BackupBase = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups"

$ProductionAppJson = Join-Path -Path $ProductionRoot -ChildPath "app.json"
$TestAppJson = Join-Path -Path $TestRoot -ChildPath "app.json"
$ChangeLog = Join-Path -Path $ProductionRoot -ChildPath "CHANGELOG.md"
$BuildScript = Join-Path -Path $RepoRoot -ChildPath "scripts\Prepare-GPIALTests.ps1"
$ReportLayoutFolder = Join-Path -Path $ProductionRoot -ChildPath "src\reportlayout"

foreach ($RequiredPath in @($ProductionAppJson, $TestAppJson, $ChangeLog, $BuildScript, $ReportLayoutFolder, $BackupBase)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path was not found: $RequiredPath"
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Encoding)
}

function Write-JsonNoBom {
    param(
        [Parameter(Mandatory)][object]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    $Json = $Value | ConvertTo-Json -Depth 100
    Write-Utf8NoBom -Path $Path -Content ($Json + [Environment]::NewLine)
}

$CurrentProductionApp = Get-Content -LiteralPath $ProductionAppJson -Raw | ConvertFrom-Json
$CurrentTestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

$AllowedProductionVersions = @("0.27.0.12", "0.27.0.13", "0.27.0.14")
$AllowedTestVersions = @("0.8.0.12", "0.8.0.13", "0.8.0.14")

if ($AllowedProductionVersions -notcontains [string]$CurrentProductionApp.version) {
    throw "Expected production source version 0.27.0.12, 0.27.0.13, or 0.27.0.14 before rollback, but found $($CurrentProductionApp.version). No files were changed."
}

if ($AllowedTestVersions -notcontains [string]$CurrentTestApp.version) {
    throw "Expected test source version 0.8.0.12, 0.8.0.13, or 0.8.0.14 before rollback, but found $($CurrentTestApp.version). No files were changed."
}

# This is the important part:
# Restore from the 0.27.0.12 script's pre-change backup, not the 0.27.0.13 backup.
# The 0.27.0.12 backup contains the last good 0.27.0.11 layout state.
$SourceBackup = Get-ChildItem -LiteralPath $BackupBase -Directory |
    Where-Object { $_.Name -like "gamer-contacts-stacked-0270012-*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($null -eq $SourceBackup) {
    throw "Could not find the pre-0.27.0.12 backup folder 'gamer-contacts-stacked-0270012-*' under $BackupBase. No files were changed."
}

$ExpectedBackupProductionAppJson = Join-Path -Path $SourceBackup.FullName -ChildPath "bc-extension\zetadocs-replacement\app.json"
$ExpectedBackupTestAppJson = Join-Path -Path $SourceBackup.FullName -ChildPath "bc-extension\zetadocs-replacement-tests\app.json"
$ExpectedBackupChangeLog = Join-Path -Path $SourceBackup.FullName -ChildPath "bc-extension\zetadocs-replacement\CHANGELOG.md"
$ExpectedBackupLayouts = Join-Path -Path $SourceBackup.FullName -ChildPath "bc-extension\zetadocs-replacement\src\reportlayout"

foreach ($RequiredBackupPath in @($ExpectedBackupProductionAppJson, $ExpectedBackupTestAppJson, $ExpectedBackupChangeLog, $ExpectedBackupLayouts)) {
    if (-not (Test-Path -LiteralPath $RequiredBackupPath)) {
        throw "Required backup path was not found: $RequiredBackupPath"
    }
}

$BackupProductionApp = Get-Content -LiteralPath $ExpectedBackupProductionAppJson -Raw | ConvertFrom-Json
$BackupTestApp = Get-Content -LiteralPath $ExpectedBackupTestAppJson -Raw | ConvertFrom-Json

if ([string]$BackupProductionApp.version -ne "0.27.0.11") {
    throw "The selected backup is not the expected 0.27.0.11 source state. It is $($BackupProductionApp.version). No files were changed."
}

if ([string]$BackupTestApp.version -ne "0.8.0.11") {
    throw "The selected backup is not the expected 0.8.0.11 test source state. It is $($BackupTestApp.version). No files were changed."
}

$SafetyBackup = Join-Path -Path $BackupBase -ChildPath ("rollback-to-last-good-0270011-as-0270015-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path $SafetyBackup -Force | Out-Null

$FilesToSafetyBackup = @($ProductionAppJson, $TestAppJson, $ChangeLog) + (Get-ChildItem -LiteralPath $ReportLayoutFolder -Filter "*.rdl" | ForEach-Object { $_.FullName })

foreach ($Path in $FilesToSafetyBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path -Path $SafetyBackup -ChildPath $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

try {
    Copy-Item -LiteralPath (Join-Path -Path $ExpectedBackupLayouts -ChildPath "*.rdl") -Destination $ReportLayoutFolder -Force
    Copy-Item -LiteralPath $ExpectedBackupChangeLog -Destination $ChangeLog -Force
    Copy-Item -LiteralPath $ExpectedBackupProductionAppJson -Destination $ProductionAppJson -Force
    Copy-Item -LiteralPath $ExpectedBackupTestAppJson -Destination $TestAppJson -Force

    $ProductionApp = Get-Content -LiteralPath $ProductionAppJson -Raw | ConvertFrom-Json
    $TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

    $MainDependency = @(
        $TestApp.dependencies |
            Where-Object { [string]$_.id -eq [string]$ProductionApp.id }
    )

    if ($MainDependency.Count -ne 1) {
        throw "Expected exactly one test dependency on production app $($ProductionApp.id), but found $($MainDependency.Count)."
    }

    $ProductionApp.version = $RestoredProductionVersion
    $TestApp.version = $RestoredTestVersion
    $MainDependency[0].version = $RestoredProductionVersion

    $ChangeLogOriginal = Get-Content -LiteralPath $ChangeLog -Raw
    $ChangeLogEntry = @"
## $RestoredProductionVersion

### Restored
- Restored report layouts to the last known-good 0.27.0.11 layout state.
- Reverted the Gamer Contacts layout changes from 0.27.0.12 and 0.27.0.13.
- Packaged the restored state as $RestoredProductionVersion so Business Central can upgrade over the bad layout versions.

### Safety
- No routing rules, sender logic, Delivery Log, SharePoint archive, or email behavior was changed.
- No package is published automatically.
- Publish production first, then tests only after production $RestoredProductionVersion is installed in the sandbox.

"@

    if ($ChangeLogOriginal -match '(?m)^# Changelog\s*$') {
        $UpdatedChangeLog = [regex]::Replace(
            $ChangeLogOriginal,
            '(?m)^# Changelog\s*$',
            "# Changelog`r`n`r`n$ChangeLogEntry",
            1
        )
    }
    else {
        throw "The changelog header was not found."
    }

    Write-JsonNoBom -Value $ProductionApp -Path $ProductionAppJson
    Write-JsonNoBom -Value $TestApp -Path $TestAppJson
    Write-Utf8NoBom -Path $ChangeLog -Content $UpdatedChangeLog

    $ProductionPackage = Join-Path -Path $ProductionRoot -ChildPath "Gamer Packaging_GPI Sales Document Email_$RestoredProductionVersion.app"
    $TestPackage = Join-Path -Path $TestRoot -ChildPath "Gamer Packaging_GPI Sales Document Email Tests_$RestoredTestVersion.app"

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " GPI restore to last good 0.27.0.11 layout state" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Restored from backup:     $($SourceBackup.FullName)"
    Write-Host "Current-state backup:     $SafetyBackup"
    Write-Host "Production version:       $RestoredProductionVersion"
    Write-Host "Test version:             $RestoredTestVersion"
    Write-Host ""
    Write-Host "Running production and test builds..." -ForegroundColor Cyan

    & $BuildScript

    if (-not (Test-Path -LiteralPath $ProductionPackage)) {
        throw "The expected production package was not created: $ProductionPackage"
    }

    if (-not (Test-Path -LiteralPath $TestPackage)) {
        throw "The expected test package was not created: $TestPackage"
    }
}
catch {
    Write-Host ""
    Write-Host "Restore build failed. Restoring the current source snapshot." -ForegroundColor Red

    foreach ($Path in $FilesToSafetyBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path -Path $SafetyBackup -ChildPath $RelativePath
        if (Test-Path -LiteralPath $BackupPath) {
            Copy-Item -LiteralPath $BackupPath -Destination $Path -Force
        }
    }

    throw
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " GPI restore build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Restored from:      $($SourceBackup.FullName)"
Write-Host "Current backup:     $SafetyBackup"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production $RestoredProductionVersion first, then tests only after production is installed in the sandbox." -ForegroundColor Yellow
