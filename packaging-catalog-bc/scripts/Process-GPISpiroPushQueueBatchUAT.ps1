[CmdletBinding()]
param(
    [switch]$Apply,
    [int]$MaxItems = 25,
    [int]$MaxAttempts = 3,
    [int]$RetryDelayMinutes = 5,
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$BcClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') { throw "This batch worker is restricted to Sandbox_NoZetadocs_UAT. Requested: $EnvironmentName" }
if ($MaxItems -lt 1 -or $MaxItems -gt 100) { throw 'MaxItems must be between 1 and 100.' }
if ($MaxAttempts -lt 1 -or $MaxAttempts -gt 10) { throw 'MaxAttempts must be between 1 and 10.' }

function Invoke-BcRequest {
    param([string]$Method, [string]$Uri, [string]$Token, $Body = $null, [string]$IfMatch = '')
    $headers = @{ Authorization = "Bearer $Token"; Accept = 'application/json' }
    if ($IfMatch) { $headers['If-Match'] = $IfMatch }
    if ($null -eq $Body) { return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -TimeoutSec $TimeoutSeconds }
    return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -ContentType 'application/json' -Body ($Body | ConvertTo-Json -Depth 20 -Compress) -TimeoutSec $TimeoutSeconds
}

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI SPIRO PUSH QUEUE BATCH WORKER UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Apply       : $($Apply.IsPresent)"
Write-Host "Max Items   : $MaxItems"
Write-Host "Max Attempts: $MaxAttempts"

$secret = (& az keyvault secret show --vault-name $KeyVaultName --name 'bc-client-secret' --query value --output tsv --only-show-errors).Trim()
if (-not $secret) { throw 'Could not retrieve BC client secret.' }
try {
    $auth = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType 'application/x-www-form-urlencoded' -Body @{
        grant_type='client_credentials'; client_id=$BcClientId; client_secret=$secret; scope='https://api.businesscentral.dynamics.com/.default'
    } -TimeoutSec $TimeoutSeconds
}
finally { $secret = $null }
$token = [string]$auth.access_token
$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companies = Invoke-BcRequest -Method GET -Uri "$bcBase/api/v2.0/companies" -Token $token
$company = @($companies.value | Where-Object name -eq $CompanyName) | Select-Object -First 1
if (-not $company) { throw "BC company '$CompanyName' not found." }
$base = "$bcBase/api/gpi/spiroIntegration/v1.0/companies($($company.id))"

$resp = Invoke-BcRequest -Method GET -Uri "$base/spiroPushRequests?`$filter=status eq 'Queued' or status eq 'Retry'&`$orderby=entryNo asc&`$top=$MaxItems" -Token $token
$rows = @($resp.value)
$now = [datetime]::UtcNow
$eligible = @($rows | Where-Object {
    $attempt = if ($null -eq $_.attemptCount) { 0 } else { [int]$_.attemptCount }
    $next = if ([string]::IsNullOrWhiteSpace([string]$_.nextAttemptAt)) { $null } else { [datetime]$_.nextAttemptAt }
    $attempt -lt $MaxAttempts -and ($null -eq $next -or $next.ToUniversalTime() -le $now)
})

Write-Host "Queued/Retry returned : $($rows.Count)"
Write-Host "Eligible now          : $($eligible.Count)"
if ($eligible.Count -eq 0) { Write-Host 'Nothing to process.' -ForegroundColor Green; return }

$singleWorker = Join-Path $PSScriptRoot 'Process-GPISpiroPushQueueUAT.ps1'
if (-not (Test-Path -LiteralPath $singleWorker)) { throw "Single-entry worker not found: $singleWorker" }

$success = 0
$failed = 0
foreach ($row in $eligible) {
    $entryNo = [int]$row.entryNo
    $queueId = [string]$row.id
    $attempt = if ($null -eq $row.attemptCount) { 0 } else { [int]$row.attemptCount }
    Write-Host "`n--- Queue Entry $entryNo ---" -ForegroundColor Yellow

    if (-not $Apply) {
        Write-Host "Would process entry $entryNo (attempt $($attempt + 1))."
        continue
    }

    $attempt++
    $workerId = "$env:COMPUTERNAME/$env:USERNAME"
    Invoke-BcRequest -Method PATCH -Uri "$base/spiroPushRequests($queueId)" -Token $token -IfMatch '*' -Body ([ordered]@{
        attemptCount = $attempt
        lastAttemptAt = [datetime]::UtcNow.ToString('o')
        workerId = $workerId
        status = 'Processing'
        lastError = ''
    }) | Out-Null

    try {
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
    }
    catch {
        $failed++
        $msg = [string]$_.Exception.Message
        if ($msg.Length -gt 250) { $msg = $msg.Substring(0,250) }
        $terminal = $attempt -ge $MaxAttempts
        $newStatus = if ($terminal) { 'Failed' } else { 'Retry' }
        $nextAttempt = if ($terminal) { $null } else { [datetime]::UtcNow.AddMinutes($RetryDelayMinutes * $attempt).ToString('o') }
        $body = [ordered]@{
            status = $newStatus
            lastError = $msg
            message = "Worker attempt $attempt failed."
            workerId = $workerId
        }
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
    }
}

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'BATCH WORKER SUMMARY' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
if ($Apply) {
    Write-Host "Success : $success"
    Write-Host "Failed  : $failed"
} else {
    Write-Host "Dry-run eligible entries : $($eligible.Count)"
    Write-Host 'No records were changed.' -ForegroundColor Green
}