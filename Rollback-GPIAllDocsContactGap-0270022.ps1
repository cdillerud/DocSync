[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$BadProductionVersion = "0.27.0.21"
$BadTestVersion = "0.8.0.21"
$RestoredProductionVersion = "0.27.0.22"
$RestoredTestVersion = "0.8.0.22"

$ProductionRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement-tests"
$BackupBase = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups"

$ProductionAppJson = Join-Path -Path $ProductionRoot -ChildPath "app.json"
$TestAppJson = Join-Path -Path $TestRoot -ChildPath "app.json"
$ChangeLog = Join-Path -Path $ProductionRoot -ChildPath "CHANGELOG.md"
$BuildScript = Join-Path -Path $RepoRoot -ChildPath "scripts\Prepare-GPIALTests.ps1"

foreach ($RequiredPath in @($ProductionAppJson, $TestAppJson, $ChangeLog, $BuildScript, $BackupBase)) {
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
    throw "Expected current production source version $BadProductionVersion before rollback, but found $($CurrentProductionApp.version). No files were changed."
}

if ([string]$CurrentTestApp.version -ne $BadTestVersion) {
    throw "Expected current test source version $BadTestVersion before rollback, but found $($CurrentTestApp.version). No files were changed."
}

$SourceBackup = Get-ChildItem -LiteralPath $BackupBase -Directory |
    Where-Object { $_.Name -like "all-docs-gamer-contacts-gap-0270021-*" } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if ($null -eq $SourceBackup) {
    throw "Could not find the all-docs 0.27.0.21 pre-change backup folder under $BackupBase. No files were changed."
}

$BackupProductionAppJson = Join-Path -Path $SourceBackup.FullName -ChildPath "bc-extension\zetadocs-replacement\app.json"
$BackupTestAppJson = Join-Path -Path $SourceBackup.FullName -ChildPath "bc-extension\zetadocs-replacement-tests\app.json"
$BackupChangeLog = Join-Path -Path $SourceBackup.FullName -ChildPath "bc-extension\zetadocs-replacement\CHANGELOG.md"
$BackupLayoutRoot = Join-Path -Path $SourceBackup.FullName -ChildPath "bc-extension\zetadocs-replacement\src\reportlayout"

foreach ($BackupPath in @($BackupProductionAppJson, $BackupTestAppJson, $BackupChangeLog, $BackupLayoutRoot)) {
    if (-not (Test-Path -LiteralPath $BackupPath)) {
        throw "Required backup path was not found: $BackupPath"
    }
}

$BackupProductionApp = Get-Content -LiteralPath $BackupProductionAppJson -Raw | ConvertFrom-Json
$BackupTestApp = Get-Content -LiteralPath $BackupTestAppJson -Raw | ConvertFrom-Json

if ([string]$BackupProductionApp.version -ne "0.27.0.20") {
    throw "Selected backup was expected to be 0.27.0.20, but is $($BackupProductionApp.version). No files were changed."
}

if ([string]$BackupTestApp.version -ne "0.8.0.20") {
    throw "Selected backup test app was expected to be 0.8.0.20, but is $($BackupTestApp.version). No files were changed."
}

$BackupLayouts = @(Get-ChildItem -LiteralPath $BackupLayoutRoot -File -Filter "*.rdl" -Recurse)
if ($BackupLayouts.Count -eq 0) {
    throw "No RDL files were found in backup layout folder: $BackupLayoutRoot"
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$SafetyBackupRoot = Join-Path -Path $BackupBase -ChildPath "rollback-all-docs-contact-gap-0270021-to-0270022-$Timestamp"
New-Item -ItemType Directory -Path $SafetyBackupRoot -Force | Out-Null

$FilesToBackup = @($ProductionAppJson, $TestAppJson, $ChangeLog)

foreach ($BackupLayout in $BackupLayouts) {
    $RelativeFromBackupLayoutRoot = $BackupLayout.FullName.Substring($BackupLayoutRoot.Length).TrimStart('\')
    $CurrentLayoutPath = Join-Path -Path (Join-Path -Path $ProductionRoot -ChildPath "src\reportlayout") -ChildPath $RelativeFromBackupLayoutRoot
    if (Test-Path -LiteralPath $CurrentLayoutPath) {
        $FilesToBackup += $CurrentLayoutPath
    }
}

foreach ($Path in $FilesToBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path -Path $SafetyBackupRoot -ChildPath $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$ProductionPackage = Join-Path -Path $ProductionRoot -ChildPath "Gamer Packaging_GPI Sales Document Email_$RestoredProductionVersion.app"
$TestPackage = Join-Path -Path $TestRoot -ChildPath "Gamer Packaging_GPI Sales Document Email Tests_$RestoredTestVersion.app"

try {
    foreach ($BackupLayout in $BackupLayouts) {
        $RelativeFromBackupLayoutRoot = $BackupLayout.FullName.Substring($BackupLayoutRoot.Length).TrimStart('\')
        $DestinationLayout = Join-Path -Path (Join-Path -Path $ProductionRoot -ChildPath "src\reportlayout") -ChildPath $RelativeFromBackupLayoutRoot
        New-Item -ItemType Directory -Path (Split-Path -Parent $DestinationLayout) -Force | Out-Null
        Copy-Item -LiteralPath $BackupLayout.FullName -Destination $DestinationLayout -Force
    }

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
- Reverted the all-document Gamer Contacts gap cleanup from 0.27.0.21.
- Restored the affected RDLC layouts from the pre-0.27.0.21 backup:
  $($SourceBackup.Name)
- This restores the 0.27.0.20 layout state and packages it as $RestoredProductionVersion so Business Central can upgrade over the bad build.

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

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " GPI rollback all-doc Gamer Contacts changes to 0.27.0.20 state" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Restored from backup: $($SourceBackup.FullName)"
    Write-Host "Current safety copy:  $SafetyBackupRoot"
    Write-Host "Layouts restored:     $($BackupLayouts.Count)"
    Write-Host "Production version:   $RestoredProductionVersion"
    Write-Host "Test version:         $RestoredTestVersion"
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
    Write-Host "Rollback build failed. Restoring current 0.27.0.21 source snapshot." -ForegroundColor Red

    foreach ($Path in $FilesToBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path -Path $SafetyBackupRoot -ChildPath $RelativePath
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
Write-Host " GPI rollback build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Restored from:      $($SourceBackup.FullName)"
Write-Host "Safety backup:      $SafetyBackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production $RestoredProductionVersion first, then tests only after production is installed in the sandbox." -ForegroundColor Yellow
