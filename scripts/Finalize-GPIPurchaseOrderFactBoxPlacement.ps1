[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"

$ProdAppJson = Join-Path $ProdRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$PurchaseFile = Join-Path $ProdRoot "src\pageextension\GPIPurchaseOrderRecordDocuments.PageExt.al"
$ChangeLog = Join-Path $ProdRoot "CHANGELOG.md"
$BuildScript = Join-Path $RepoRoot "scripts\Prepare-GPIALTests.ps1"

foreach ($Path in @(
    $ProdAppJson,
    $TestAppJson,
    $PurchaseFile,
    $ChangeLog,
    $BuildScript
)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required file was not found: $Path"
    }
}

$ProdApp = Get-Content -LiteralPath $ProdAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

if ([string]$ProdApp.version -ne "0.26.0.5") {
    throw "Expected production version 0.26.0.5, but found $($ProdApp.version)."
}

if ([string]$TestApp.version -ne "0.7.1.7") {
    throw "Expected test version 0.7.1.7, but found $($TestApp.version)."
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Encoding)
}

$PurchaseText = Get-Content -LiteralPath $PurchaseFile -Raw
$ChangeLogText = Get-Content -LiteralPath $ChangeLog -Raw

# Replace only the layout operation immediately governing GPIRecordDocuments.
$PlacementPattern =
    '(?is)\b(?:addafter|addbefore|addfirst|addlast)\s*\(\s*[^)]*\s*\)' +
    '(?=\s*\{\s*part\s*\(\s*GPIRecordDocuments\s*;)'

$PlacementMatches = @([regex]::Matches($PurchaseText, $PlacementPattern))

if ($PlacementMatches.Count -ne 1) {
    throw "Expected exactly one placement operation for GPIRecordDocuments, but found $($PlacementMatches.Count)."
}

$CurrentPlacement = $PlacementMatches[0].Value
$CorrectPlacement = 'addafter("Purchase Order Documents Sent")'

Write-Host ""
Write-Host "Current placement: $CurrentPlacement"
Write-Host "Correct placement: $CorrectPlacement"

$CorrectedPurchaseText = [regex]::Replace(
    $PurchaseText,
    $PlacementPattern,
    [System.Text.RegularExpressions.MatchEvaluator]{
        param($Match)
        return $CorrectPlacement
    },
    1
)

# Keep the unpublished 0.26.0.5 changelog accurate.
$CorrectedChangeLogText = $ChangeLogText
$CorrectedChangeLogText = $CorrectedChangeLogText.Replace(
    'after Boyer control Posting Description',
    'after Boyer control Purchase Order Documents Sent'
)
$CorrectedChangeLogText = $CorrectedChangeLogText.Replace(
    'after Boyer control "Posting Description"',
    'after Boyer control "Purchase Order Documents Sent"'
)
$CorrectedChangeLogText = $CorrectedChangeLogText.Replace(
    'after Boyer control Page50005',
    'after Boyer control Purchase Order Documents Sent'
)

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\finalize-po-factbox-$Timestamp"

$PurchaseBackup = Join-Path $BackupRoot (
    $PurchaseFile.Substring($RepoRoot.Length).TrimStart('\')
)
$ChangeLogBackup = Join-Path $BackupRoot (
    $ChangeLog.Substring($RepoRoot.Length).TrimStart('\')
)

New-Item -ItemType Directory -Path (Split-Path -Parent $PurchaseBackup) -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $ChangeLogBackup) -Force | Out-Null

Copy-Item -LiteralPath $PurchaseFile -Destination $PurchaseBackup -Force
Copy-Item -LiteralPath $ChangeLog -Destination $ChangeLogBackup -Force

Write-Utf8NoBom -Path $PurchaseFile -Content $CorrectedPurchaseText
Write-Utf8NoBom -Path $ChangeLog -Content $CorrectedChangeLogText

Write-Host ""
Write-Host "Running production and test builds..." -ForegroundColor Cyan

try {
    & $BuildScript
}
catch {
    Write-Host ""
    Write-Host "The exact Boyer anchor did not build. Restoring the prior files." -ForegroundColor Red

    Copy-Item -LiteralPath $PurchaseBackup -Destination $PurchaseFile -Force
    Copy-Item -LiteralPath $ChangeLogBackup -Destination $ChangeLog -Force

    throw
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " Purchase Order FactBox placement finalized" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Anchor:              Purchase Order Documents Sent"
Write-Host "Production version:  0.26.0.5"
Write-Host "Test version:        0.7.1.7"
Write-Host "Backup:              $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish both packages only to Sandbox_5_5_2026, then refresh the Testing panel and run the complete suite." -ForegroundColor Yellow
