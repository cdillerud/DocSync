[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs",
    [string]$GoodBackupName = "gamer-contacts-stacked-0270012-20260716-174416"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RestoredProductionVersion = "0.27.0.16"
$RestoredTestVersion = "0.8.0.16"

$ProductionRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement-tests"
$BackupBase = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups"
$GoodBackupRoot = Join-Path -Path $BackupBase -ChildPath $GoodBackupName

$ProductionAppJson = Join-Path -Path $ProductionRoot -ChildPath "app.json"
$TestAppJson = Join-Path -Path $TestRoot -ChildPath "app.json"
$ChangeLog = Join-Path -Path $ProductionRoot -ChildPath "CHANGELOG.md"
$BuildScript = Join-Path -Path $RepoRoot -ChildPath "scripts\Prepare-GPIALTests.ps1"
$ReportLayoutFolder = Join-Path -Path $ProductionRoot -ChildPath "src\reportlayout"

$BackupProductionAppJson = Join-Path -Path $GoodBackupRoot -ChildPath "bc-extension\zetadocs-replacement\app.json"
$BackupTestAppJson = Join-Path -Path $GoodBackupRoot -ChildPath "bc-extension\zetadocs-replacement-tests\app.json"
$BackupChangeLog = Join-Path -Path $GoodBackupRoot -ChildPath "bc-extension\zetadocs-replacement\CHANGELOG.md"
$BackupReportLayoutFolder = Join-Path -Path $GoodBackupRoot -ChildPath "bc-extension\zetadocs-replacement\src\reportlayout"

foreach ($RequiredPath in @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog,
    $BuildScript,
    $ReportLayoutFolder,
    $GoodBackupRoot,
    $BackupProductionAppJson,
    $BackupTestAppJson,
    $BackupChangeLog,
    $BackupReportLayoutFolder
)) {
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

function Get-AppVersion {
    param([Parameter(Mandatory)][string]$Path)

    $App = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    return [string]$App.version
}

function Test-GoodSalesOrderLayout {
    param([Parameter(Mandatory)][string]$LayoutPath)

    if (-not (Test-Path -LiteralPath $LayoutPath)) {
        throw "Sales Order layout was not found at $LayoutPath"
    }

    $Content = Get-Content -LiteralPath $LayoutPath -Raw
    $Lower = $Content.ToLowerInvariant()

    $ContactsIndex = $Lower.IndexOf("gamer contacts")
    $ContactWindow = ""
    if ($ContactsIndex -ge 0) {
        $Start = [Math]::Max(0, $ContactsIndex - 700)
        $Length = [Math]::Min(3500, $Content.Length - $Start)
        $ContactWindow = $Content.Substring($Start, $Length).ToLowerInvariant()
    }

    $Problems = @()

    if (-not $Lower.Contains("order date")) {
        $Problems += "missing Order Date"
    }

    if (-not $Lower.Contains("requested receive by")) {
        $Problems += "missing Requested Receive By"
    }

    if (-not $Lower.Contains("gamer contacts")) {
        $Problems += "missing Gamer Contacts"
    }

    if (-not $ContactWindow.Contains("vbcrlf")) {
        $Problems += "Gamer Contacts expression does not contain vbCrLf near the contacts block"
    }

    if ($Problems.Count -gt 0) {
        throw "Restored Sales Order layout validation failed: $($Problems -join '; ')"
    }
}

$BackupProductionVersion = Get-AppVersion -Path $BackupProductionAppJson
$BackupTestVersion = Get-AppVersion -Path $BackupTestAppJson

if ($BackupProductionVersion -ne "0.27.0.11") {
    throw "The selected backup '$GoodBackupName' is not the expected 0.27.0.11 backup. It is $BackupProductionVersion. No files were changed."
}

if ($BackupTestVersion -ne "0.8.0.11") {
    throw "The selected backup '$GoodBackupName' is not the expected 0.8.0.11 backup. It is $BackupTestVersion. No files were changed."
}

Test-GoodSalesOrderLayout -LayoutPath (Join-Path -Path $BackupReportLayoutFolder -ChildPath "GPISalesOrderConfirmationBranded.rdl")

$SafetyBackup = Join-Path -Path $BackupBase -ChildPath ("restore-exact-good-backup-to-0270016-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path $SafetyBackup -Force | Out-Null

$FilesToSafetyBackup = @($ProductionAppJson, $TestAppJson, $ChangeLog) + (Get-ChildItem -LiteralPath $ReportLayoutFolder -Filter "*.rdl" | ForEach-Object { $_.FullName })

foreach ($Path in $FilesToSafetyBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path -Path $SafetyBackup -ChildPath $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$ProductionPackage = Join-Path -Path $ProductionRoot -ChildPath "Gamer Packaging_GPI Sales Document Email_$RestoredProductionVersion.app"
$TestPackage = Join-Path -Path $TestRoot -ChildPath "Gamer Packaging_GPI Sales Document Email Tests_$RestoredTestVersion.app"

try {
    # Replace the entire RDL layout set with the exact known-good backup layout set.
    Get-ChildItem -LiteralPath $ReportLayoutFolder -Filter "*.rdl" | Remove-Item -Force
    Copy-Item -LiteralPath (Join-Path -Path $BackupReportLayoutFolder -ChildPath "*.rdl") -Destination $ReportLayoutFolder -Force

    # Restore app/changelog from the same known-good backup, then bump forward to a safe upgrade version.
    Copy-Item -LiteralPath $BackupChangeLog -Destination $ChangeLog -Force
    Copy-Item -LiteralPath $BackupProductionAppJson -Destination $ProductionAppJson -Force
    Copy-Item -LiteralPath $BackupTestAppJson -Destination $TestAppJson -Force

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
- Restored the entire RDLC layout set from exact backup:
  $GoodBackupName
- This backup is the verified 0.27.0.11 layout state.
- Packaged as $RestoredProductionVersion so Business Central can upgrade over the bad later layout versions.

### Safety
- No routing rules, sender logic, Delivery Log, SharePoint archive, or email behavior was changed.
- No package is published automatically.
- Publish production $RestoredProductionVersion first, then tests only after production is installed in the sandbox.

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

    Test-GoodSalesOrderLayout -LayoutPath (Join-Path -Path $ReportLayoutFolder -ChildPath "GPISalesOrderConfirmationBranded.rdl")

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " GPI exact restore to verified 0.27.0.11 layout state" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Restored from:       $GoodBackupRoot"
    Write-Host "Current backup:      $SafetyBackup"
    Write-Host "Production version:  $RestoredProductionVersion"
    Write-Host "Test version:        $RestoredTestVersion"
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
    Write-Host "Exact restore build failed. Restoring the current source snapshot." -ForegroundColor Red

    foreach ($Path in $FilesToSafetyBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path -Path $SafetyBackup -ChildPath $RelativePath
        if (Test-Path -LiteralPath $BackupPath) {
            Copy-Item -LiteralPath $BackupPath -Destination $Path -Force
        }
    }

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    throw
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " GPI exact restore build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Restored from:      $GoodBackupRoot"
Write-Host "Current backup:     $SafetyBackup"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production $RestoredProductionVersion first, then tests only after production is installed in the sandbox." -ForegroundColor Yellow
