#requires -Version 7.0

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$RawBase = 'https://raw.githubusercontent.com/cdillerud/DocSync/agent/parity-cutover-hardening-20260827/scripts'
$TempRoot = Join-Path $env:TEMP ('gpi-sep20-hardgates-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))

$Scripts = @(
    'Invoke-GPI-Migration-Recoverability-HardGate.ps1',
    'Invoke-GPI-AP-Warehouse-Recipient-Authority-HardGate.ps1',
    'Invoke-GPI-Sep20-AP-Warehouse-Cutover-HardGate.ps1'
)

function Section([string]$Name) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Name -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

Section '1. HARD SAFETY'
if (-not (Test-Path -LiteralPath $RepoRoot)) { throw "Repo not found: $RepoRoot" }
$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Could not determine Git branch.' }
if ($Branch -ne $ExpectedBranch) { throw "Expected branch '$ExpectedBranch', found '$Branch'." }

Write-Host "Repo       : $RepoRoot"
Write-Host "Branch     : $Branch"
Write-Host 'Mode       : READ ONLY'
Write-Host 'Production : NOT TOUCHED' -ForegroundColor Green

Section '2. ACQUIRE / PARSE CURRENT GATES'
New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
$LocalScripts = @()

foreach ($Name in $Scripts) {
    $Path = Join-Path $TempRoot $Name
    Invoke-WebRequest -Uri "$RawBase/$Name" -OutFile $Path -UseBasicParsing -ErrorAction Stop

    $Tokens = $null
    $Errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path -LiteralPath $Path),[ref]$Tokens,[ref]$Errors) | Out-Null
    if ($Errors.Count -gt 0) {
        throw "Parser failure in $Name :: $((@($Errors | ForEach-Object Message)) -join '; ')"
    }

    $LocalScripts += $Path
    Write-Host "PASS  $Name" -ForegroundColor Green
}

Section '3. MIGRATION / RECOVERABILITY'
& $LocalScripts[0]
if ($LASTEXITCODE -ne 0) { throw "Migration/recoverability hard gate exited $LASTEXITCODE." }

Section '4. AP / WAREHOUSE RECIPIENT AUTHORITY'
& $LocalScripts[1]
if ($LASTEXITCODE -ne 0) { throw "AP/Warehouse recipient-authority hard gate exited $LASTEXITCODE." }

Section '5. CONSOLIDATED SEP 20 CUTOVER LEDGER'
& $LocalScripts[2]
if ($LASTEXITCODE -ne 0) { throw "Consolidated cutover hard gate exited $LASTEXITCODE." }

Section '6. RESULT'
Write-Host 'SEP 20 LOCAL AP/WAREHOUSE HARD-GATE STACK: PASS' -ForegroundColor Green
Write-Host 'Production: NOT TOUCHED'
Write-Host 'No routing changes'
Write-Host 'No email sends'
Write-Host 'No migration writes'
Write-Host 'No Git reset / clean / checkout'
