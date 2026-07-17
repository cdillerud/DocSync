[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.7"
$ExpectedTestVersion = "0.8.0.7"
$NewProductionVersion = "0.27.0.8"
$NewTestVersion = "0.8.0.8"

$ProductionRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement-tests"

$ProductionAppJson = Join-Path -Path $ProductionRoot -ChildPath "app.json"
$TestAppJson = Join-Path -Path $TestRoot -ChildPath "app.json"
$ChangeLog = Join-Path -Path $ProductionRoot -ChildPath "CHANGELOG.md"
$BuildScript = Join-Path -Path $RepoRoot -ChildPath "scripts\Prepare-GPIALTests.ps1"
$ReportLayoutFolder = Join-Path -Path $ProductionRoot -ChildPath "src\reportlayout"
$BackupRootBase = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups"

$RequiredPaths = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog,
    $BuildScript,
    $ReportLayoutFolder,
    $BackupRootBase
)

foreach ($RequiredPath in $RequiredPaths) {
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

$LayoutFileNames = @(
    "GPIBlanketSalesOrderBranded.rdl",
    "GPICustomerOpenOrderStatusBranded.rdl",
    "GPICustomerStatementBranded.rdl",
    "GPIDropShipPurchaseOrderBranded.rdl",
    "GPIPickTicket.rdl",
    "GPIPrepaymentNotice.rdl",
    "GPIPurchaseCreditMemoBranded.rdl",
    "GPIPurchaseReturnOrderBranded.rdl",
    "GPIPurchaseReturnPickTicketBranded.rdl",
    "GPISalesCreditMemoBranded.rdl",
    "GPISalesInvoiceBranded.rdl",
    "GPISalesOrderConfirmationBranded.rdl",
    "GPISalesReturnAuthorizationBranded.rdl",
    "GPISalesReturnWarehouseNotificationBranded.rdl",
    "GPITransferPickListBranded.rdl",
    "GPITransferReceiptNotificationBranded.rdl",
    "GPIWarehousePurchaseOrderBranded.rdl",
    "GPIWarehouseReceivingNoticeBranded.rdl"
)

$LayoutFiles = $LayoutFileNames | ForEach-Object { Join-Path -Path $ReportLayoutFolder -ChildPath $_ }

foreach ($LayoutFile in $LayoutFiles) {
    if (-not (Test-Path -LiteralPath $LayoutFile)) {
        throw "Layout file was not found: $LayoutFile"
    }
}

$CandidateBackups = @(
    Get-ChildItem -LiteralPath $BackupRootBase -Directory -ErrorAction Stop |
        Where-Object { $_.Name -like "footer-address-only-027007-v2-*" -or $_.Name -like "footer-address-only-027007-*" } |
        Sort-Object LastWriteTime -Descending
)

if ($CandidateBackups.Count -lt 1) {
    throw "No footer-address-only 0.27.0.7 backup folder was found under $BackupRootBase. No files were changed."
}

$SourceBackupRoot = $null
foreach ($Candidate in $CandidateBackups) {
    $AllLayoutsExist = $true
    foreach ($LayoutName in $LayoutFileNames) {
        $BackupLayoutPath = Join-Path -Path $Candidate.FullName -ChildPath ("bc-extension\zetadocs-replacement\src\reportlayout\" + $LayoutName)
        if (-not (Test-Path -LiteralPath $BackupLayoutPath)) {
            $AllLayoutsExist = $false
            break
        }
    }

    if ($AllLayoutsExist) {
        $SourceBackupRoot = $Candidate.FullName
        break
    }
}

if ([string]::IsNullOrWhiteSpace($SourceBackupRoot)) {
    throw "Footer backup folders were found, but none contained all expected report layouts. No files were changed."
}

$ProductionApp = Get-Content -LiteralPath $ProductionAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

if ([string]$ProductionApp.version -ne $ExpectedProductionVersion) {
    throw "Expected production version $ExpectedProductionVersion, but found $($ProductionApp.version). No files were changed."
}

if ([string]$TestApp.version -ne $ExpectedTestVersion) {
    throw "Expected test version $ExpectedTestVersion, but found $($TestApp.version). No files were changed."
}

$MainDependency = @(
    $TestApp.dependencies |
        Where-Object { [string]$_.id -eq [string]$ProductionApp.id }
)

if ($MainDependency.Count -ne 1) {
    throw "Expected exactly one test dependency on production app $($ProductionApp.id), but found $($MainDependency.Count). No files were changed."
}

$FilesToBackup = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog
) + $LayoutFiles

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$NewBackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\revert-footer-027008-$Timestamp"
New-Item -ItemType Directory -Path $NewBackupRoot -Force | Out-Null

foreach ($Path in $FilesToBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path -Path $NewBackupRoot -ChildPath $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$RestoredLayouts = @{}
foreach ($LayoutName in $LayoutFileNames) {
    $LiveLayoutPath = Join-Path -Path $ReportLayoutFolder -ChildPath $LayoutName
    $BackupLayoutPath = Join-Path -Path $SourceBackupRoot -ChildPath ("bc-extension\zetadocs-replacement\src\reportlayout\" + $LayoutName)
    $RestoredLayouts[$LiveLayoutPath] = Get-Content -LiteralPath $BackupLayoutPath -Raw
}

$ProductionApp.version = $NewProductionVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProductionVersion

$ChangeLogOriginal = Get-Content -LiteralPath $ChangeLog -Raw
$ChangeLogEntry = @"
## $NewProductionVersion

### Changed
- Reverted the 0.27.0.7 PageFooter layout pass.
- Restored the report layout files from the pre-0.27.0.7 backup so report body/header information boxes return to their previous sizing.

### Safety
- No recipient, sender, routing-rule, Delivery Log, SharePoint archive, or email behavior was changed.
- No package is published automatically.
- Publish only to Sandbox_NoZetadocs_UAT or Sandbox_5_5_2026 unless Chad explicitly approves another environment.

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
    throw "The changelog header was not found. No files were changed."
}

$ProductionPackage = Join-Path -Path $ProductionRoot -ChildPath "Gamer Packaging_GPI Sales Document Email_$NewProductionVersion.app"
$TestPackage = Join-Path -Path $TestRoot -ChildPath "Gamer Packaging_GPI Sales Document Email Tests_$NewTestVersion.app"

try {
    foreach ($LayoutPath in $RestoredLayouts.Keys) {
        Write-Utf8NoBom -Path $LayoutPath -Content $RestoredLayouts[$LayoutPath]
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
    Write-Host " GPI footer rollback build 0.27.0.8" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version:        $NewProductionVersion"
    Write-Host "Test version:              $NewTestVersion"
    Write-Host "Restored layouts from:     $SourceBackupRoot"
    Write-Host "Current-state backup:      $NewBackupRoot"
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
    Write-Host "The footer rollback build failed. Restoring the current 0.27.0.7 files." -ForegroundColor Red

    foreach ($Path in $FilesToBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path -Path $NewBackupRoot -ChildPath $RelativePath
        Copy-Item -LiteralPath $BackupPath -Destination $Path -Force
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
Write-Host " GPI 0.27.0.8 footer rollback build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Restored from:      $SourceBackupRoot"
Write-Host "Backup:             $NewBackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish both packages only to the active UAT sandbox if you want to replace 0.27.0.7 there." -ForegroundColor Yellow
