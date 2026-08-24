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

function Save-Utf8NoBom {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][string]$Content)
    [System.IO.File]::WriteAllText($Path,$Content,[System.Text.UTF8Encoding]::new($false))
}

function Replace-Once {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Label
    )
    $first = $Text.IndexOf($Old,[System.StringComparison]::Ordinal)
    if ($first -lt 0) { throw "0.31 patch anchor not found: $Label" }
    $second = $Text.IndexOf($Old,$first + $Old.Length,[System.StringComparison]::Ordinal)
    if ($second -ge 0) { throw "0.31 patch anchor is not unique: $Label" }
    return $Text.Substring(0,$first) + $New + $Text.Substring($first + $Old.Length)
}

$appJson = Join-Path $ProjectPath 'app.json'
$batchWorker = Join-Path $ProjectPath 'scripts\Process-GPISpiroPushQueueBatchUAT.ps1'
$taskName = 'GPI Spiro Push Worker UAT Unattended'

foreach ($file in @($appJson,$batchWorker)) {
    if (-not (Test-Path -LiteralPath $file)) { throw "Required 0.30 file not found: $file" }
}

Write-Step 'SAFETY PRECHECK'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task -and [string]$task.State -ne 'Disabled') {
    throw "Scheduled task '$taskName' must be Disabled before patching the live worker. Current state: $($task.State)"
}
Write-Host 'Unattended scheduled task is disabled.' -ForegroundColor Green

Write-Step 'PRECHECK 0.30'
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.30.0.0') { throw "Expected local app version 0.30.0.0. Found $($app.version)." }
$batch = Get-Content -LiteralPath $batchWorker -Raw
foreach ($marker in @("status = 'Processing'",'$newStatus','spiroPushRequests','$singleWorker')) {
    if (-not $batch.Contains($marker)) { throw "Required 0.30 batch-worker marker not found: $marker" }
}
if ($batch.Contains('GPI 0.31 QUEUE AUDIT HARDENING')) { throw '0.31 queue audit hardening already appears to be present.' }
Write-Host '0.30 batch worker confirmed.' -ForegroundColor Green

Write-Step 'BUMP APP VERSION TO 0.31.0.0'
$appText = Get-Content -LiteralPath $appJson -Raw
$appText = Replace-Once -Text $appText -Old '"version": "0.30.0.0"' -New '"version": "0.31.0.0"' -Label 'app version'
Save-Utf8NoBom -Path $appJson -Content $appText
Write-Host "Patched: $appJson" -ForegroundColor DarkGreen

Write-Step 'HARDEN BATCH SUCCESS AUDIT STATE'
$batch = Get-Content -LiteralPath $batchWorker -Raw
$oldSuccess = @'
        & $singleWorker -EntryNo $entryNo -Apply
        $success++
'@
$newSuccess = @'
        & $singleWorker -EntryNo $entryNo -Apply

        # GPI 0.31 QUEUE AUDIT HARDENING
        # The single-entry worker owns the Success transition. The batch wrapper
        # clears retry-only audit fields so a recovered request does not retain
        # a stale backoff timestamp or error after eventual success.
        Invoke-BcRequest -Method PATCH -Uri "$base/spiroPushRequests($queueId)" -Token $token -IfMatch '*' -Body ([ordered]@{
            nextAttemptAt = '0001-01-01T00:00:00Z'
            lastError = ''
        }) | Out-Null
        $success++
'@
$batch = Replace-Once -Text $batch -Old $oldSuccess -New $newSuccess -Label 'success block'

Write-Step 'MIRROR RETRY AND FAILED STATE TO QUOTE'
$oldCatchTail = @'
        if ($nextAttempt) { $body.nextAttemptAt = $nextAttempt }
        Invoke-BcRequest -Method PATCH -Uri "$base/spiroPushRequests($queueId)" -Token $token -IfMatch '*' -Body $body | Out-Null
        Write-Warning "Entry $entryNo failed: $msg"
'@
$newCatchTail = @'
        if ($nextAttempt) {
            $body.nextAttemptAt = $nextAttempt
        }
        else {
            $body.nextAttemptAt = '0001-01-01T00:00:00Z'
        }
        Invoke-BcRequest -Method PATCH -Uri "$base/spiroPushRequests($queueId)" -Token $token -IfMatch '*' -Body $body | Out-Null

        # GPI 0.31 QUEUE AUDIT HARDENING
        # Mirror the queue retry/terminal state onto the quote so the quote card
        # cannot remain misleadingly Queued after a worker failure.
        try {
            $quoteNo = [int]$row.quoteNo
            $quoteResponse = Invoke-BcRequest -Method GET -Uri "$base/spiroQuoteLinks?`$filter=quoteNo eq $quoteNo" -Token $token
            $quote = @($quoteResponse.value) | Select-Object -First 1
            if (-not $quote) { throw "Packaging Quote $quoteNo was not returned by the Spiro quote-link API." }
            $quoteId = [string]$quote.id
            if ([string]::IsNullOrWhiteSpace($quoteId)) { throw "Packaging Quote $quoteNo API row did not include an id." }
            $quoteMessage = if ($terminal) { "Spiro push failed after $attempt attempt(s): $msg" } else { "Spiro push attempt $attempt failed and is scheduled for retry: $msg" }
            if ($quoteMessage.Length -gt 250) { $quoteMessage = $quoteMessage.Substring(0,250) }
            Invoke-BcRequest -Method PATCH -Uri "$base/spiroQuoteLinks($quoteId)" -Token $token -IfMatch '*' -Body ([ordered]@{
                spiroPushStatus = $newStatus
                spiroPushMessage = $quoteMessage
            }) | Out-Null
        }
        catch {
            Write-Warning "Entry $entryNo queue state was updated, but quote failure-state mirroring also failed: $($_.Exception.Message)"
        }

        Write-Warning "Entry $entryNo failed: $msg"
'@
$batch = Replace-Once -Text $batch -Old $oldCatchTail -New $newCatchTail -Label 'failure catch tail'
Save-Utf8NoBom -Path $batchWorker -Content $batch
Write-Host "Patched: $batchWorker" -ForegroundColor DarkGreen

Write-Step 'VALIDATE 0.31'
$checks = @(
    @{ Path=$appJson; Pattern='"version": "0.31.0.0"'; Label='0.31 app version' },
    @{ Path=$batchWorker; Pattern='GPI 0.31 QUEUE AUDIT HARDENING'; Label='0.31 audit marker' },
    @{ Path=$batchWorker; Pattern="nextAttemptAt = '0001-01-01T00:00:00Z'"; Label='stale next-attempt clearing' },
    @{ Path=$batchWorker; Pattern='spiroPushStatus = $newStatus'; Label='quote failure-state mirroring' },
    @{ Path=$batchWorker; Pattern='spiroPushMessage = $quoteMessage'; Label='quote failure message mirroring' }
)
foreach ($check in $checks) {
    $raw = Get-Content -LiteralPath $check.Path -Raw
    if (-not $raw.Contains($check.Pattern)) { throw "Validation failed: $($check.Label)" }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host ''
Write-Host '0.31 Spiro queue audit hardening applied successfully.' -ForegroundColor Green
Write-Host 'Scheduled task remains disabled. No publish or deployment was performed.' -ForegroundColor Yellow
Write-Host 'Next: build, run a controlled success-path test, then run an intentional failure/retry test before re-enabling.' -ForegroundColor Cyan
