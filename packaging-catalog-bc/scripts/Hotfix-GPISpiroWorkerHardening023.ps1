[CmdletBinding()]
param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step {
    param([Parameter(Mandatory)][string]$Text)
    Write-Host "`n== $Text ==" -ForegroundColor Cyan
}

$appJson = Join-Path $ProjectPath 'app.json'
$singleWorker = Join-Path $ProjectPath 'scripts\Process-GPISpiroPushQueueUAT.ps1'
$batchWorker = Join-Path $ProjectPath 'scripts\Process-GPISpiroPushQueueBatchUAT.ps1'

foreach ($file in @($appJson, $singleWorker, $batchWorker)) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Required 0.23 file not found: $file"
    }
}

Write-Step 'PRECHECK 0.23'
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.23.0.0') {
    throw "Expected local app version 0.23.0.0. Found $($app.version)."
}
Write-Host '0.23 app version confirmed.' -ForegroundColor Green

Write-Step 'ALLOW BATCH PROCESSING HANDOFF IN SINGLE-ENTRY WORKER'
$text = Get-Content -LiteralPath $singleWorker -Raw
$old = @'
if ([string]$queue.status -ne 'Queued') { throw "Queue entry $EntryNo is not Queued. Current status: $($queue.status)" }
'@
$new = @'
$queueStatus = [string]$queue.status
if ($queueStatus -notin @('Queued', 'Processing')) {
    throw "Queue entry $EntryNo is not Queued or Processing. Current status: $queueStatus"
}
'@
if ($text.Contains($old)) {
    $text = $text.Replace($old, $new)
    [System.IO.File]::WriteAllText($singleWorker, $text, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Patched: $singleWorker" -ForegroundColor DarkGreen
}
elif ($text.Contains("-notin @('Queued', 'Processing')")) {
    Write-Host 'Already present: single-worker Processing handoff.' -ForegroundColor DarkYellow
}
else {
    throw 'Single-worker queue status anchor not found.'
}

Write-Step 'REMOVE STALE LASTEXITCODE CHECK FROM BATCH WORKER'
$text = Get-Content -LiteralPath $batchWorker -Raw
$old = @'
        & $singleWorker -EntryNo $entryNo -Apply
        if ($LASTEXITCODE -ne 0) { throw "Single-entry worker exited with code $LASTEXITCODE." }
        $success++
'@
$new = @'
        & $singleWorker -EntryNo $entryNo -Apply
        $success++
'@
if ($text.Contains($old)) {
    $text = $text.Replace($old, $new)
    [System.IO.File]::WriteAllText($batchWorker, $text, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Patched: $batchWorker" -ForegroundColor DarkGreen
}
elif (-not $text.Contains('Single-entry worker exited with code $LASTEXITCODE.')) {
    Write-Host 'Already removed: stale LASTEXITCODE check.' -ForegroundColor DarkYellow
}
else {
    throw 'Batch-worker LASTEXITCODE anchor not found.'
}

Write-Step 'VALIDATE 0.23 WORKER HARDENING'
$singleRaw = Get-Content -LiteralPath $singleWorker -Raw
$batchRaw = Get-Content -LiteralPath $batchWorker -Raw

$checks = @(
    @{ Passed = $singleRaw.Contains("-notin @('Queued', 'Processing')"); Label = 'Processing handoff accepted by single worker' },
    @{ Passed = $batchRaw.Contains("$newStatus = if ($terminal) { 'Failed' } else { 'Retry' }"); Label = 'Retry workflow present' },
    @{ Passed = $batchRaw.Contains('nextAttemptAt = $nextAttempt'); Label = 'Retry scheduling present' },
    @{ Passed = $batchRaw.Contains("status = 'Processing'"); Label = 'Processing claim present' },
    @{ Passed = -not $batchRaw.Contains('Single-entry worker exited with code $LASTEXITCODE.'); Label = 'stale LASTEXITCODE check removed' }
)

foreach ($check in $checks) {
    if (-not $check.Passed) { throw "Validation failed: $($check.Label)" }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.23 worker hardening hotfix applied successfully." -ForegroundColor Green
Write-Host 'No AL source was changed by this hotfix.' -ForegroundColor Cyan
Write-Host 'The existing 0.23 app build remains valid; publish it before testing the batch worker because the new queue API fields must exist in BC.' -ForegroundColor Cyan
