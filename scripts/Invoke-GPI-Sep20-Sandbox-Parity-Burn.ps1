#requires -Version 7.0

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$ExpectedBranch = 'feature/phase-3-record-documents'
$RawBase = 'https://raw.githubusercontent.com/cdillerud/DocSync/agent/parity-cutover-hardening-20260827/scripts'
$TempRoot = Join-Path $env:TEMP ('gpi-sep20-sandbox-burn-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$Build184Name = 'Build-Publish-GPI-PO-Recipient-Hard-Parity-Gate-0.27.0.184.ps1'
$GateStackName = 'Invoke-GPI-Sep20-OneShot-Local-Parity-Gates.ps1'

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
Write-Host "Repo        : $RepoRoot"
Write-Host "Branch      : $Branch"
Write-Host 'Environment : Sandbox_08142026_GamerDocs'
Write-Host 'Production  : HARD BLOCKED' -ForegroundColor Green
Write-Host 'Git         : no reset / clean / checkout'

Section '2. ACQUIRE CURRENT GUARDED TOOLING'
New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
$Build184 = Join-Path $TempRoot $Build184Name
$GateStack = Join-Path $TempRoot $GateStackName

foreach ($Item in @(
    @{ Name = $Build184Name; Path = $Build184 },
    @{ Name = $GateStackName; Path = $GateStack }
)) {
    Invoke-WebRequest -Uri "$RawBase/$($Item.Name)" -OutFile $Item.Path -UseBasicParsing -ErrorAction Stop
    $Tokens = $null
    $Errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path -LiteralPath $Item.Path),[ref]$Tokens,[ref]$Errors) | Out-Null
    if ($Errors.Count -gt 0) {
        throw "Parser failure in $($Item.Name): $((@($Errors | ForEach-Object Message)) -join '; ')"
    }
    Write-Host "PASS  $($Item.Name)" -ForegroundColor Green
}

Section '3. BUILD / PUBLISH MAIN .184 HARD GATE TO SANDBOX'
& $Build184
if ($LASTEXITCODE -ne 0) { throw "Main .184 build/publish exited $LASTEXITCODE." }

$MainAppJson = Join-Path $RepoRoot 'bc-extension\zetadocs-replacement\app.json'
$MainApp = Get-Content -LiteralPath $MainAppJson -Raw | ConvertFrom-Json
if ([string]$MainApp.version -ne '0.27.0.184') {
    throw "Expected local main source 0.27.0.184 after guarded build/publish, found $($MainApp.version)."
}
Write-Host 'PASS  main .184 source/package/publish stage' -ForegroundColor Green

Section '4. RUN COMPLETE READ-ONLY LOCAL PARITY STACK'
& $GateStack
if ($LASTEXITCODE -ne 0) { throw "Sep 20 local parity gate stack exited $LASTEXITCODE." }

Section '5. EXTERNAL RUNTIME GATE REMAINS'
Write-Host 'The source/package hardening stack is complete.' -ForegroundColor Green
Write-Host 'One BC runtime assertion remains: GPI PO Bucket Evidence Audit -> Run Hard Parity Gate.' -ForegroundColor Yellow
Write-Host 'That action executes the existing exact retained Production To/CC/BCC evidence against current sandbox resolvers.'
Write-Host 'No email is sent by the audit action.'

Section '6. RESULT'
Write-Host 'SEP 20 SANDBOX PARITY BURN: SOURCE/PACKAGE STACK PASS' -ForegroundColor Green
Write-Host 'Production: NOT TOUCHED'
Write-Host 'Main target: GPI Sales Document Email 0.27.0.184'
Write-Host 'Bridge target: GPI Zetadocs Pilot Bridge 0.1.0.21 already evidenced installed'
Write-Host 'Remaining external boundary: execute one read-only BC runtime hard-gate action'
