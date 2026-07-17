[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProdVersion = "0.26.0.5"
$ExpectedTestVersion = "0.7.1.7"
$NewProdVersion = "0.26.0.6"
$NewTestVersion = "0.7.1.8"

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"

$ProdAppJson = Join-Path $ProdRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLog = Join-Path $ProdRoot "CHANGELOG.md"
$PageExtensionFolder = Join-Path $ProdRoot "src\pageextension"
$SalesHideFile = Join-Path $PageExtensionFolder "GPIHideSalesIncomingDocs.PageExt.al"
$PurchaseHideFile = Join-Path $PageExtensionFolder "GPIHidePurchaseIncomingDocs.PageExt.al"
$BuildScript = Join-Path $RepoRoot "scripts\Prepare-GPIALTests.ps1"

foreach ($Path in @(
    $ProdAppJson,
    $TestAppJson,
    $ChangeLog,
    $PageExtensionFolder,
    $BuildScript
)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required path was not found: $Path"
    }
}

if (
    (Test-Path -LiteralPath $SalesHideFile) -or
    (Test-Path -LiteralPath $PurchaseHideFile)
) {
    throw "One or both incoming-document FactBox page-extension files already exist. No files were changed."
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

$ProdApp = Get-Content -LiteralPath $ProdAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

if ([string]$ProdApp.version -ne $ExpectedProdVersion) {
    throw "Expected production version $ExpectedProdVersion, but found $($ProdApp.version). No files were changed."
}

if ([string]$TestApp.version -ne $ExpectedTestVersion) {
    throw "Expected test version $ExpectedTestVersion, but found $($TestApp.version). No files were changed."
}

$MainAppId = [string]$ProdApp.id
$MainDependency = @(
    $TestApp.dependencies |
        Where-Object { [string]$_.id -eq $MainAppId }
)

if ($MainDependency.Count -ne 1) {
    throw "Expected exactly one test dependency on production app $MainAppId, but found $($MainDependency.Count). No files were changed."
}

# Confirm the control has not already been hidden elsewhere in this app.
$ExistingIncomingDocModifications = @(
    Get-ChildItem -LiteralPath $ProdRoot -Recurse -File -Filter "*.al" |
        Select-String -Pattern 'modify\s*\(\s*IncomingDocAttachFactBox\s*\)'
)

if ($ExistingIncomingDocModifications.Count -gt 0) {
    Write-Host "Existing IncomingDocAttachFactBox modification(s):" -ForegroundColor Yellow
    $ExistingIncomingDocModifications |
        Select-Object Path, LineNumber, Line |
        Format-Table -AutoSize

    throw "IncomingDocAttachFactBox is already modified in the production source. No files were changed."
}

# Collect all object IDs already declared in this project.
$UsedIds = New-Object 'System.Collections.Generic.HashSet[int]'
$ObjectDeclarationPattern =
    '(?im)^\s*(?:table|tableextension|page|pageextension|pagecustomization|' +
    'codeunit|report|reportextension|xmlport|query|controladdin|enum|' +
    'enumextension|interface|permissionset|permissionsetextension|profile|' +
    'profileextension)\s+(\d+)\b'

foreach ($AlFile in Get-ChildItem -LiteralPath $ProdRoot -Recurse -File -Filter "*.al") {
    $Content = Get-Content -LiteralPath $AlFile.FullName -Raw

    foreach ($Match in [regex]::Matches($Content, $ObjectDeclarationPattern)) {
        [void]$UsedIds.Add([int]$Match.Groups[1].Value)
    }
}

$AvailableIds = New-Object 'System.Collections.Generic.List[int]'

foreach ($Range in @($ProdApp.idRanges)) {
    $FromId = [int]$Range.from
    $ToId = [int]$Range.to

    for ($Id = $FromId; $Id -le $ToId; $Id++) {
        if (-not $UsedIds.Contains($Id)) {
            $AvailableIds.Add($Id)
        }

        if ($AvailableIds.Count -ge 2) {
            break
        }
    }

    if ($AvailableIds.Count -ge 2) {
        break
    }
}

if ($AvailableIds.Count -lt 2) {
    throw "Two unused object IDs could not be found in the production app idRanges. No files were changed."
}

$SalesPageExtensionId = $AvailableIds[0]
$PurchasePageExtensionId = $AvailableIds[1]

$SalesSource = @"
pageextension $SalesPageExtensionId "GPI Hide SO Incoming Docs" extends "Sales Order"
{
    layout
    {
        modify(IncomingDocAttachFactBox)
        {
            Visible = false;
        }
    }
}
"@

$PurchaseSource = @"
pageextension $PurchasePageExtensionId "GPI Hide PO Incoming Docs" extends "Purchase Order"
{
    layout
    {
        modify(IncomingDocAttachFactBox)
        {
            Visible = false;
        }
    }
}
"@

$OriginalProdAppJson = Get-Content -LiteralPath $ProdAppJson -Raw
$OriginalTestAppJson = Get-Content -LiteralPath $TestAppJson -Raw
$OriginalChangeLog = Get-Content -LiteralPath $ChangeLog -Raw

$ProdApp.version = $NewProdVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProdVersion

$ChangeLogEntry = @"
## $NewProdVersion

### Changed
- Hid the native Microsoft Incoming Document Files FactBox on Sales Orders.
- Hid the native Microsoft Incoming Document Files FactBox on Purchase Orders.
- The underlying Incoming Documents and E-Document functionality remains installed and available elsewhere in Business Central.

### Technical
- Modified the Base Application control `IncomingDocAttachFactBox` on Sales Order and Purchase Order pages.
- No GPI document upload, SharePoint archive, email, report, routing, or delivery-log behavior was changed.
- Publish only to Sandbox_5_5_2026 unless Chad explicitly approves another environment.

"@

if ($OriginalChangeLog -match '(?m)^# Changelog\s*$') {
    $UpdatedChangeLog = [regex]::Replace(
        $OriginalChangeLog,
        '(?m)^# Changelog\s*$',
        "# Changelog`r`n`r`n$ChangeLogEntry",
        1
    )
}
else {
    $UpdatedChangeLog = $ChangeLogEntry + "`r`n" + $OriginalChangeLog
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\hide-native-incoming-doc-factboxes-$Timestamp"

foreach ($Path in @($ProdAppJson, $TestAppJson, $ChangeLog)) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path $BackupRoot $RelativePath

    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

try {
    Write-Utf8NoBom -Path $SalesHideFile -Content $SalesSource
    Write-Utf8NoBom -Path $PurchaseHideFile -Content $PurchaseSource
    Write-JsonNoBom -Value $ProdApp -Path $ProdAppJson
    Write-JsonNoBom -Value $TestApp -Path $TestAppJson
    Write-Utf8NoBom -Path $ChangeLog -Content $UpdatedChangeLog

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " Native Incoming Document FactBox removal" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Sales Order page extension ID:    $SalesPageExtensionId"
    Write-Host "Purchase Order page extension ID: $PurchasePageExtensionId"
    Write-Host "Production version:               $NewProdVersion"
    Write-Host "Test version:                     $NewTestVersion"
    Write-Host "Backup:                           $BackupRoot"
    Write-Host ""
    Write-Host "Running production and test builds..." -ForegroundColor Cyan

    & $BuildScript
}
catch {
    Write-Host ""
    Write-Host "The build failed. Restoring the repository to the pre-change state." -ForegroundColor Red

    if (Test-Path -LiteralPath $SalesHideFile) {
        Remove-Item -LiteralPath $SalesHideFile -Force
    }

    if (Test-Path -LiteralPath $PurchaseHideFile) {
        Remove-Item -LiteralPath $PurchaseHideFile -Force
    }

    Write-Utf8NoBom -Path $ProdAppJson -Content $OriginalProdAppJson
    Write-Utf8NoBom -Path $TestAppJson -Content $OriginalTestAppJson
    Write-Utf8NoBom -Path $ChangeLog -Content $OriginalChangeLog

    throw
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Native Incoming Document FactBoxes hidden" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package version: $NewProdVersion"
Write-Host "Test package version:       $NewTestVersion"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish both packages only to Sandbox_5_5_2026, refresh the VS Code Testing panel, and run the complete test suite." -ForegroundColor Yellow
