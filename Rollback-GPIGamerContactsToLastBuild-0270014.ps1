[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$BadProductionVersion = "0.27.0.13"
$BadTestVersion = "0.8.0.13"
$RestoredProductionVersion = "0.27.0.14"
$RestoredTestVersion = "0.8.0.14"

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

if ([string]$CurrentProductionApp.version -ne $BadProductionVersion) {
    throw "Expected production source version $BadProductionVersion before rollback, but found $($CurrentProductionApp.version). No files were changed."
}

if ([string]$CurrentTestApp.version -ne $BadTestVersion) {
    throw "Expected test source version $BadTestVersion before rollback, but found $($CurrentTestApp.version). No files were changed."
}

$SourceBackup = Get-ChildItem -LiteralPath $BackupBase -Directory |
    Where-Object { $_.Name -like "gamer-contacts-stacked-0270013-*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($null -eq $SourceBackup) {
    throw "Could not find the 0.27.0.13 pre-change backup folder under $BackupBase. No files were changed."
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

$SafetyBackup = Join-Path -Path $BackupBase -ChildPath ("rollback-from-0270013-to-0270014-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path $SafetyBackup -Force | Out-Null

$FilesToSafetyBackup = @($ProductionAppJson, $TestAppJson, $ChangeLog) + (Get-ChildItem -LiteralPath $ReportLayoutFolder -Filter "*.rdl" | ForEach-Object { $_.FullName })

foreach ($Path in $FilesToSafetyBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path -Path $SafetyBackup -ChildPath $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

try {
    # Restore layouts and changelog from the pre-0.27.0.13 backup.
    Copy-Item -LiteralPath (Join-Path -Path $ExpectedBackupLayouts -ChildPath "*.rdl") -Destination $ReportLayoutFolder -Force
    Copy-Item -LiteralPath $ExpectedBackupChangeLog -Destination $ChangeLog -Force

    # Restore app.json files, then bump to 0.27.0.14 / 0.8.0.14 so BC can accept this as an upgrade over 0.27.0.13.
    Copy-Item -LiteralPath $ExpectedBackupProductionAppJson -Destination $ProductionAppJson -Force
    Copy-Item -LiteralPath $ExpectedBackupTestAppJson -Destination $TestAppJson -Force

    $ProductionApp = Get-Content -LiteralPath $ProductionAppJson -Raw | ConvertFrom-Json
    $TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

    if ([string]$ProductionApp.version -ne "0.27.0.12") {
        throw "Backup production app.json was expected to be 0.27.0.12, but it is $($ProductionApp.version)."
    }

    if ([string]$TestApp.version -ne "0.8.0.12") {
        throw "Backup test app.json was expected to be 0.8.0.12, but it is $($TestApp.version)."
    }

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
- Restored report layouts to the last accepted build state before 0.27.0.13.
- Reverted the Gamer Contacts layout experiment from 0.27.0.13.
- This is functionally the 0.27.0.12 layout state repackaged as $RestoredProductionVersion so Business Central can upgrade over the bad build.

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
    Write-Host " GPI rollback from 0.27.0.13 to previous layout state" -ForegroundColor Cyan
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
    Write-Host "Rollback build failed. Restoring the current 0.27.0.13 source snapshot." -ForegroundColor Red

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
Write-Host " GPI rollback build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Restored from:      $($SourceBackup.FullName)"
Write-Host "Current backup:     $SafetyBackup"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production $RestoredProductionVersion first, then tests only after production is installed in the sandbox." -ForegroundColor Yellow
