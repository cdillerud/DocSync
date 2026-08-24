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

function Replace-Once {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Label
    )
    $first = $Text.IndexOf($Old, [System.StringComparison]::Ordinal)
    if ($first -lt 0) { throw "0.23 patch anchor not found: $Label" }
    $second = $Text.IndexOf($Old, $first + $Old.Length, [System.StringComparison]::Ordinal)
    if ($second -ge 0) { throw "0.23 patch anchor is not unique: $Label" }
    return $Text.Substring(0, $first) + $New + $Text.Substring($first + $Old.Length)
}

function Save-PatchedFile {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Content)
    $backup = "$Path.pre-0.23.bak"
    if (-not (Test-Path -LiteralPath $backup)) { Copy-Item -LiteralPath $Path -Destination $backup -Force }
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Patched: $Path" -ForegroundColor DarkGreen
}

$appJson = Join-Path $ProjectPath 'app.json'
$queueTable = Join-Path $ProjectPath 'src\Tables\GPISpiroPushQueue.Table.al'
$queueApi = Join-Path $ProjectPath 'src\Pages\GPISpiroPushQueueAPI.Page.al'
$batchWorker = Join-Path $ProjectPath 'scripts\Process-GPISpiroPushQueueBatchUAT.ps1'

foreach ($file in @($appJson, $queueTable, $queueApi)) {
    if (-not (Test-Path -LiteralPath $file)) { throw "Required 0.22 file not found: $file" }
}

Write-Step 'PRECHECK 0.22'
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.22.0.0') { throw "Expected local app version 0.22.0.0. Found $($app.version)." }
$tableRaw = Get-Content -LiteralPath $queueTable -Raw
$apiRaw = Get-Content -LiteralPath $queueApi -Raw
if (-not $tableRaw.Contains('table 71106 "GPI Spiro Push Queue"')) { throw '0.22 push queue table marker not found.' }
if (-not $apiRaw.Contains("EntitySetName = 'spiroPushRequests'")) { throw '0.22 push queue API marker not found.' }
if ($tableRaw.Contains('"Attempt Count"')) { throw '0.23 worker hardening already appears to be present.' }
Write-Host '0.22 source precheck passed.' -ForegroundColor Green

Write-Step 'BUMP APP VERSION TO 0.23.0.0'
$appText = Get-Content -LiteralPath $appJson -Raw
$appText = Replace-Once -Text $appText -Old '"version": "0.22.0.0"' -New '"version": "0.23.0.0"' -Label 'app version'
Save-PatchedFile -Path $appJson -Content $appText

Write-Step 'ADD RETRY AND WORKER AUDIT FIELDS'
$text = Get-Content -LiteralPath $queueTable -Raw
$anchor = @'
        field(8; Message; Text[250])
        {
            Caption = 'Message';
        }
'@
$replacement = $anchor + @'
        field(9; "Attempt Count"; Integer)
        {
            Caption = 'Attempt Count';
        }
        field(10; "Last Attempt At"; DateTime)
        {
            Caption = 'Last Attempt At';
        }
        field(11; "Next Attempt At"; DateTime)
        {
            Caption = 'Next Attempt At';
        }
        field(12; "Last Error"; Text[250])
        {
            Caption = 'Last Error';
        }
        field(13; "Worker ID"; Text[100])
        {
            Caption = 'Worker ID';
        }
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'queue Message field'
Save-PatchedFile -Path $queueTable -Content $text

Write-Step 'EXPOSE RETRY FIELDS THROUGH QUEUE API'
$text = Get-Content -LiteralPath $queueApi -Raw
$anchor = @'
                field(message; Rec.Message)
                {
                    Caption = 'Message';
                }
'@
$replacement = $anchor + @'
                field(attemptCount; Rec."Attempt Count")
                {
                    Caption = 'Attempt Count';
                }
                field(lastAttemptAt; Rec."Last Attempt At")
                {
                    Caption = 'Last Attempt At';
                }
                field(nextAttemptAt; Rec."Next Attempt At")
                {
                    Caption = 'Next Attempt At';
                }
                field(lastError; Rec."Last Error")
                {
                    Caption = 'Last Error';
                }
                field(workerId; Rec."Worker ID")
                {
                    Caption = 'Worker ID';
                }
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'queue API Message field'
Save-PatchedFile -Path $queueApi -Content $text

Write-Step 'CREATE BATCH WORKER WRAPPER'
$workerText = @'
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
        if ($LASTEXITCODE -ne 0) { throw "Single-entry worker exited with code $LASTEXITCODE." }
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
        if ($nextAttempt) { $body.nextAttemptAt = $nextAttempt }
        Invoke-BcRequest -Method PATCH -Uri "$base/spiroPushRequests($queueId)" -Token $token -IfMatch '*' -Body $body | Out-Null
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
'@
[System.IO.File]::WriteAllText($batchWorker, $workerText, [System.Text.UTF8Encoding]::new($false))
Write-Host "Created: $batchWorker" -ForegroundColor DarkGreen

Write-Step 'VALIDATE 0.23 PATCH'
$checks = @(
    @{ Path=$appJson; Pattern='"version": "0.23.0.0"'; Label='0.23 app version' },
    @{ Path=$queueTable; Pattern='field(9; "Attempt Count"; Integer)'; Label='attempt count field' },
    @{ Path=$queueTable; Pattern='field(12; "Last Error"; Text[250])'; Label='last error field' },
    @{ Path=$queueApi; Pattern='field(attemptCount; Rec."Attempt Count")'; Label='attempt count API field' },
    @{ Path=$queueApi; Pattern='field(workerId; Rec."Worker ID")'; Label='worker ID API field' },
    @{ Path=$batchWorker; Pattern='GPI SPIRO PUSH QUEUE BATCH WORKER UAT'; Label='batch worker script' },
    @{ Path=$batchWorker; Pattern="status = 'Retry'"; Label='retry workflow' }
)
foreach ($check in $checks) {
    $raw = Get-Content -LiteralPath $check.Path -Raw
    if (-not $raw.Contains($check.Pattern)) { throw "Validation failed: $($check.Label)" }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.23 Spiro worker hardening patch applied successfully." -ForegroundColor Green
Write-Host 'No publish, deployment, or scheduled task was created.' -ForegroundColor Yellow
Write-Host 'Next: run the normal Packaging Catalog build.' -ForegroundColor Cyan
