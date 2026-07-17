[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs",
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProdRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"
$ProdAppJson = Join-Path $ProdRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ArchivePage = Join-Path $ProdRoot "src\page\GPISharePointArchiveSetup.Page.al"
$BuildScript = Join-Path $RepoRoot "scripts\Prepare-GPIALTests.ps1"

foreach ($Path in @($ProdAppJson, $TestAppJson, $ArchivePage)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required file was not found: $Path"
    }
}

$ProdApp = Get-Content -LiteralPath $ProdAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

if ([string]$ProdApp.version -ne "0.26.0.5") {
    throw "Expected production version 0.26.0.5, but found $($ProdApp.version). No files were changed."
}

if ([string]$TestApp.version -ne "0.7.1.7") {
    throw "Expected test version 0.7.1.7, but found $($TestApp.version). No files were changed."
}

$PageText = Get-Content -LiteralPath $ArchivePage -Raw

$Marker = '    local procedure RefreshAccountStatus()'
$FirstMarker = $PageText.IndexOf($Marker, [System.StringComparison]::Ordinal)

if ($FirstMarker -lt 0) {
    throw "RefreshAccountStatus was not found. No files were changed."
}

$SecondMarker = $PageText.IndexOf(
    $Marker,
    $FirstMarker + $Marker.Length,
    [System.StringComparison]::Ordinal
)

if ($SecondMarker -ge 0) {
    throw "More than one RefreshAccountStatus declaration was found. No files were changed."
}

$CanonicalTail = @'
    local procedure RefreshAccountStatus()
    var
        ArchiveMgt: Codeunit "GPI SharePoint Archive";
    begin
        ArchiveMgt.GetArchiveAccountHealth(
            ArchiveAccountName,
            ArchiveConnectorName,
            ArchiveAccountStatus,
            ArchiveAccountStyle);
    end;

    var
        ArchiveAccountStatus: Text[50];
        ArchiveAccountName: Text[250];
        ArchiveConnectorName: Text[100];
        ArchiveAccountStyle: Text;
}
'@

$RepairedPageText = $PageText.Substring(0, $FirstMarker) + $CanonicalTail

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\repair-archive-setup-page-$Timestamp"
$RelativePath = $ArchivePage.Substring($RepoRoot.Length).TrimStart('\')
$BackupPath = Join-Path $BackupRoot $RelativePath

New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
Copy-Item -LiteralPath $ArchivePage -Destination $BackupPath -Force

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
    $ArchivePage,
    $RepairedPageText,
    $Utf8NoBom
)

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " GPI SharePoint Archive Setup page repaired" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production version: 0.26.0.5"
Write-Host "Test version:       0.7.1.7"
Write-Host "Backup:             $BackupPath"

if (-not $SkipBuild) {
    if (-not (Test-Path -LiteralPath $BuildScript)) {
        throw "The page was repaired, but the build script was not found: $BuildScript"
    }

    Write-Host ""
    Write-Host "Running production and test builds..." -ForegroundColor Cyan
    & $BuildScript

    if ($LASTEXITCODE -ne 0) {
        throw "The page was repaired, but the build returned exit code $LASTEXITCODE."
    }
}
else {
    Write-Host ""
    Write-Host "Build skipped. Run:"
    Write-Host "& `"$BuildScript`""
}

Write-Host ""
Write-Host "Do not publish to Production." -ForegroundColor Yellow
Write-Host "After both builds pass, publish only to Sandbox_5_5_2026." -ForegroundColor Yellow
