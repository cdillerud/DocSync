#requires -Version 7.0

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$BridgeRoot = Join-Path $RepoRoot 'bc-extension\gpi-zetadocs-pilot-bridge'
$PackagePath = Join-Path $BridgeRoot 'Gamer Packaging_GPI Zetadocs Pilot Bridge_0.1.0.21.app'

$RawBase = 'https://raw.githubusercontent.com/cdillerud/DocSync/agent/parity-cutover-hardening-20260827/scripts'
$BuildUrl = "$RawBase/Build-GPI-Zetadocs-First-Batch-Stale-Recovery-Bridge-0.1.0.21-REV2.ps1"
$PublishUrl = "$RawBase/Publish-GPI-Zetadocs-Pilot-Bridge-0.1.0.21-To-GamerDocs-Sandbox.ps1"

$TempRoot = Join-Path $env:TEMP ('gpi-bridge-021-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$BuildScript = Join-Path $TempRoot 'Build-GPI-Zetadocs-First-Batch-Stale-Recovery-Bridge-0.1.0.21-REV2.ps1'
$PublishScript = Join-Path $TempRoot 'Publish-GPI-Zetadocs-Pilot-Bridge-0.1.0.21-To-GamerDocs-Sandbox.ps1'

function Section([string]$Name) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Name -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

Section '1. LOCAL DELIVERY WORKTREE SAFETY'

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    throw "Repo root not found: $RepoRoot"
}

$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'Could not determine current Git branch.'
}

if ($Branch -ne $ExpectedBranch) {
    throw "SAFETY STOP: expected branch '$ExpectedBranch', found '$Branch'."
}

if (-not (Test-Path -LiteralPath $BridgeRoot)) {
    throw "Bridge source not found: $BridgeRoot"
}

Write-Host "Repo       : $RepoRoot"
Write-Host "Branch     : $Branch"
Write-Host 'Production : HARD BLOCKED by downstream publisher' -ForegroundColor Green
Write-Host 'Git        : no reset / clean / checkout'

Section '2. ACQUIRE CURRENT GUARDED BUILD/PUBLISH TOOLING'

New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

Invoke-WebRequest -Uri $BuildUrl -OutFile $BuildScript -UseBasicParsing -ErrorAction Stop
Invoke-WebRequest -Uri $PublishUrl -OutFile $PublishScript -UseBasicParsing -ErrorAction Stop

foreach ($Path in @($BuildScript,$PublishScript)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Failed to acquire required script: $Path"
    }

    $Tokens = $null
    $Errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        (Resolve-Path -LiteralPath $Path),
        [ref]$Tokens,
        [ref]$Errors
    ) | Out-Null

    if ($Errors.Count -gt 0) {
        $Detail = ($Errors | ForEach-Object { $_.Message }) -join '; '
        throw "Downloaded script failed PowerShell parser validation: $Path :: $Detail"
    }
}

Write-Host 'Build tool   : parser PASS' -ForegroundColor Green
Write-Host 'Publish tool : parser PASS' -ForegroundColor Green

Section '3. BUILD BRIDGE .21 FROM CURRENT LOCAL .20 SOURCE'

& $BuildScript
if ($LASTEXITCODE -ne 0) {
    throw "Bridge .21 builder exited with code $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) {
    throw "Builder completed but package was not found: $PackagePath"
}

$Hash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToUpperInvariant()
$Package = Get-Item -LiteralPath $PackagePath

Write-Host ''
Write-Host 'BUILD VERIFIED' -ForegroundColor Green
Write-Host "Package : $($Package.FullName)"
Write-Host "Bytes   : $($Package.Length)"
Write-Host "SHA256  : $Hash"

Section '4. HASH-LOCKED SANDBOX PUBLISH'

& $PublishScript -ExpectedSha256 $Hash
if ($LASTEXITCODE -ne 0) {
    throw "Bridge .21 publisher exited with code $LASTEXITCODE."
}

Section '5. ONE-SHOT RESULT'

Write-Host 'BRIDGE .21 BUILD + SANDBOX PUBLISH COMPLETE' -ForegroundColor Green
Write-Host ''
Write-Host 'Installed target : GPI Zetadocs Pilot Bridge 0.1.0.21'
Write-Host 'Environment      : Sandbox_08142026_GamerDocs'
Write-Host "Package SHA256   : $Hash"
Write-Host 'Production       : NOT TOUCHED'
Write-Host 'Routing          : NOT CHANGED'
Write-Host 'Migration data   : NOT CHANGED BY THIS RUNNER'
Write-Host 'Git              : NOT RESET / CLEANED / CHECKED OUT'
Write-Host ''
Write-Host 'NEXT PARITY WORK: run the migration recoverability validation and continue the AP/Warehouse cutover gate.'
