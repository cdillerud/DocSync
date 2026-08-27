#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$BuildOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$ScriptRoot = Join-Path $RepoRoot 'scripts'
$OutputRoot = Join-Path $RepoRoot '.gpi-diagnostics\sep20-recipient-burndown'

$BuildPublish = Join-Path $ScriptRoot 'Build-Publish-GPI-PO-Recipient-Hard-Parity-Gate-0.27.0.184.ps1'
$AuthorityGate = Join-Path $ScriptRoot 'Invoke-GPI-AP-Warehouse-Recipient-Authority-HardGate.ps1'

function Section([string]$Text) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

Section '1. SEPTEMBER 20 RECIPIENT PARITY BURN-DOWN PRECHECK'

if (-not (Test-Path -LiteralPath $RepoRoot)) {
    throw "Repo not found: $RepoRoot"
}

$Branch = (& git -C $RepoRoot branch --show-current).Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'Could not determine current Git branch.'
}
if ($Branch -ne $ExpectedBranch) {
    throw "Expected branch '$ExpectedBranch', found '$Branch'."
}

foreach ($Path in @($BuildPublish,$AuthorityGate)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required parity gate script missing: $Path"
    }
}

$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$RunRoot = Join-Path $OutputRoot $Stamp
New-Item -ItemType Directory -Path $RunRoot -Force | Out-Null
$Transcript = Join-Path $RunRoot 'Sep20-Recipient-Parity-BurnDown.log'

Start-Transcript -LiteralPath $Transcript -Force | Out-Null
try {
    Write-Host "Repo        : $RepoRoot"
    Write-Host "Branch      : $Branch"
    Write-Host "Run output  : $RunRoot"
    Write-Host "BuildOnly   : $BuildOnly"
    Write-Host 'Production  : NOT A TARGET'

    Section '2. BUILD / PUBLISH PO HARD PARITY GATE'

    if ($BuildOnly) {
        & $BuildPublish -BuildOnly
    }
    else {
        & $BuildPublish
    }

    if ($LASTEXITCODE -ne 0) {
        throw "PO hard-parity gate build/publish failed with exit code $LASTEXITCODE."
    }

    Section '3. AP / WAREHOUSE RECIPIENT AUTHORITY HARD GATE'

    & $AuthorityGate
    $AuthorityExit = $LASTEXITCODE

    if ($AuthorityExit -eq 2) {
        throw 'Recipient authority has PARITY RISK rows remaining. Burn-down is not complete.'
    }

    if ($AuthorityExit -ne 0) {
        throw "Recipient authority hard gate failed with exit code $AuthorityExit."
    }

    Section '4. RESULT'

    Write-Host 'SEPTEMBER 20 RECIPIENT PARITY BURN-DOWN CODE GATES PASS' -ForegroundColor Green
    Write-Host ''
    Write-Host 'Closed by this run:'
    Write-Host '  - .184 hard-gate source safety / compile / sandbox deployment gate'
    Write-Host '  - AP/Warehouse recipient-authority source gate'
    Write-Host ''
    Write-Host 'Runtime exact-bucket evidence still remains authoritative and must show no source-found mismatch.'
}
finally {
    Stop-Transcript | Out-Null
    Write-Host "Transcript: $Transcript"
}
