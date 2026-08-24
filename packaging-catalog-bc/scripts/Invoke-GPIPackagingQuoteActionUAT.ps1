[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [int]$QuoteNo,

    [Parameter(Mandatory)]
    [ValidateSet(
        'evaluate',
        'readyForReview',
        'approve',
        'reject',
        'reopen'
    )]
    [string]$Action,

    [switch]$Confirmed,

    [string]$TenantId =
        'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc',

    [string]$EnvironmentName =
        'Sandbox_NoZetadocs_UAT',

    [string]$CompanyId =
        '7d84c6d5-81e2-eb11-86df-00224822baa7'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "STOP: this executor is UAT-only. Environment received: $EnvironmentName"
}

if ($QuoteNo -eq 67) {
    throw 'STOP: Packaging Quote 67 is protected and may not be used by this executor.'
}

if (-not (Get-Command Get-AzAccessToken -ErrorAction SilentlyContinue)) {
    throw 'Get-AzAccessToken is not available. Connect with Az.Accounts first.'
}

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host 'GPI PACKAGING QUOTE CONTROLLED WRITE ACTION - UAT' -ForegroundColor Cyan
Write-Host ('=' * 72) -ForegroundColor Cyan
Write-Host "Environment : $EnvironmentName"
Write-Host "Quote       : $QuoteNo"
Write-Host "Action      : $Action"
Write-Host "Confirmed   : $Confirmed"

$tokenResult =
    Get-AzAccessToken `
        -ResourceUrl 'https://api.businesscentral.dynamics.com'

if ($tokenResult.Token -is [Security.SecureString]) {
    $accessToken =
        [System.Net.NetworkCredential]::new(
            '',
            $tokenResult.Token
        ).Password
}
else {
    $accessToken = [string]$tokenResult.Token
}

if ([string]::IsNullOrWhiteSpace($accessToken)) {
    throw 'Business Central API token was not returned.'
}

$headers = @{
    Authorization = "Bearer $accessToken"
    Accept        = 'application/json'
}

$writeHeaders = @{
    Authorization  = "Bearer $accessToken"
    Accept         = 'application/json'
    'Content-Type' = 'application/json'
}

$baseUri =
    "https://api.businesscentral.dynamics.com/v2.0/" +
    "$TenantId/$EnvironmentName/api/gpi/packagingQuotes/v1.0/" +
    "companies($CompanyId)"

$filter = [uri]::EscapeDataString("entryNo eq $QuoteNo")

$summarySelect = @(
    'id',
    'entryNo',
    'status',
    'customerNo',
    'lineCount',
    'approvalLineCount',
    'hasPricingExceptions',
    'decisionNote',
    'actionContractVersion',
    'actionResource',
    'canEvaluate',
    'canMoveToReadyForReview',
    'canApprove',
    'canReject',
    'canReopen',
    'rejectDecisionNoteRequired',
    'allowedWriteActions',
    'writeConfirmationRequired',
    'recommendedNextAction'
) -join ','

$summaryUri =
    "$baseUri/packagingQuoteSummaries" +
    "?`$filter=$filter&`$select=$summarySelect"

$quoteUri =
    "$baseUri/packagingQuotes?`$filter=$filter"

function Get-CurrentSummary {
    $response =
        Invoke-RestMethod `
            -Method Get `
            -Uri $summaryUri `
            -Headers $headers `
            -ErrorAction Stop

    $rows = @($response.value)

    if ($rows.Count -ne 1) {
        throw "STOP: expected one summary row for Quote $QuoteNo; received $($rows.Count)."
    }

    return $rows[0]
}

function Get-CurrentQuote {
    $response =
        Invoke-RestMethod `
            -Method Get `
            -Uri $quoteUri `
            -Headers $headers `
            -ErrorAction Stop

    $rows = @($response.value)

    if ($rows.Count -ne 1) {
        throw "STOP: expected one quote row for Quote $QuoteNo; received $($rows.Count)."
    }

    return $rows[0]
}

function Test-ActionAllowed {
    param(
        [Parameter(Mandatory)]
        $Summary,

        [Parameter(Mandatory)]
        [string]$RequestedAction
    )

    if ([string]$Summary.actionContractVersion -ne '1.0') {
        throw "STOP: unsupported action contract version: $($Summary.actionContractVersion)"
    }

    if ([string]$Summary.actionResource -ne 'packagingQuotes') {
        throw "STOP: unexpected action resource: $($Summary.actionResource)"
    }

    $allowed =
        @(
            ([string]$Summary.allowedWriteActions).Split(
                ',',
                [System.StringSplitOptions]::RemoveEmptyEntries
            )
        ) |
        ForEach-Object { $_.Trim() }

    return ($RequestedAction -in $allowed)
}

function Get-ExpectedStatus {
    param(
        [Parameter(Mandatory)]
        [string]$RequestedAction,

        [Parameter(Mandatory)]
        [string]$StatusBefore
    )

    switch ($RequestedAction) {
        'readyForReview' { return 'Ready' }
        'approve'        { return 'Approved' }
        'reject'         { return 'Rejected' }
        'reopen'         { return 'Draft' }
        'evaluate'       { return $StatusBefore }
        default          { throw "Unsupported action: $RequestedAction" }
    }
}

# ------------------------------------------------------------------------
# INITIAL READ
# ------------------------------------------------------------------------
$beforeSummary = Get-CurrentSummary
$beforeQuote   = Get-CurrentQuote

Write-Host ''
Write-Host 'CURRENT CONTRACT' -ForegroundColor Yellow

[pscustomobject]@{
    QuoteNo                   = $beforeSummary.entryNo
    Status                    = $beforeSummary.status
    ContractVersion           = $beforeSummary.actionContractVersion
    AllowedWriteActions       = $beforeSummary.allowedWriteActions
    WriteConfirmationRequired = $beforeSummary.writeConfirmationRequired
    RecommendedNextAction     = $beforeSummary.recommendedNextAction
} | Format-List

if (-not (Test-ActionAllowed -Summary $beforeSummary -RequestedAction $Action)) {
    throw (
        "STOP: action '$Action' is not currently allowed for Quote $QuoteNo. " +
        "Allowed: '$($beforeSummary.allowedWriteActions)'"
    )
}

if ($beforeSummary.writeConfirmationRequired -ne $true) {
    throw 'STOP: current contract does not advertise confirmation-required write execution.'
}

if (-not $Confirmed) {
    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor Yellow
    Write-Host 'DRY RUN ONLY - NO WRITE EXECUTED' -ForegroundColor Yellow
    Write-Host ('=' * 72) -ForegroundColor Yellow
    Write-Host "Quote  : $QuoteNo"
    Write-Host "Action : $Action"
    Write-Host ''
    Write-Host 'The action is currently permitted by the live 0.36 contract.'
    Write-Host "Re-run with -Confirmed to execute it." -ForegroundColor Cyan
    return
}

# ------------------------------------------------------------------------
# REVALIDATE IMMEDIATELY BEFORE WRITE
# ------------------------------------------------------------------------
Write-Host ''
Write-Host 'REVALIDATING CONTRACT BEFORE WRITE...' -ForegroundColor Cyan

$liveSummary = Get-CurrentSummary
$liveQuote   = Get-CurrentQuote

if (-not (Test-ActionAllowed -Summary $liveSummary -RequestedAction $Action)) {
    throw (
        "STOP: action '$Action' became unavailable before execution. " +
        "Current allowed actions: '$($liveSummary.allowedWriteActions)'"
    )
}

if ([string]$liveQuote.status -ne [string]$beforeQuote.status) {
    throw (
        "STOP: quote status changed between initial read and execution. " +
        "Before: $($beforeQuote.status); Current: $($liveQuote.status)"
    )
}

$quoteId = [string]$liveQuote.id

if ([string]::IsNullOrWhiteSpace($quoteId)) {
    throw 'STOP: quote SystemId was not returned.'
}

$expectedStatus =
    Get-ExpectedStatus `
        -RequestedAction $Action `
        -StatusBefore ([string]$liveQuote.status)

$actionUri =
    "$baseUri/packagingQuotes($quoteId)/Microsoft.NAV.$Action"

$evaluationBefore = [string]$liveQuote.lastEvaluatedAt

# ------------------------------------------------------------------------
# EXECUTE
# ------------------------------------------------------------------------
Write-Host ''
Write-Host 'EXECUTING CONFIRMED ACTION' -ForegroundColor Yellow
Write-Host "URI    : $actionUri"
Write-Host "Action : $Action"

Invoke-RestMethod `
    -Method Post `
    -Uri $actionUri `
    -Headers $writeHeaders `
    -Body '{}' `
    -ErrorAction Stop |
    Out-Null

# ------------------------------------------------------------------------
# VERIFY
# ------------------------------------------------------------------------
$afterQuote   = Get-CurrentQuote
$afterSummary = Get-CurrentSummary

Write-Host ''
Write-Host 'POST-ACTION STATE' -ForegroundColor Yellow

[pscustomobject]@{
    QuoteNo             = $afterQuote.entryNo
    Status              = $afterQuote.status
    LastEvaluatedAt     = $afterQuote.lastEvaluatedAt
    AllowedWriteActions = $afterSummary.allowedWriteActions
    RecommendedNext     = $afterSummary.recommendedNextAction
} | Format-List

if ([string]$afterQuote.status -ne $expectedStatus) {
    throw (
        "STOP: action executed but resulting status was unexpected. " +
        "Expected: $expectedStatus; Actual: $($afterQuote.status)"
    )
}

if ($Action -eq 'evaluate') {
    $evaluationAfter = [string]$afterQuote.lastEvaluatedAt

    if ([string]::IsNullOrWhiteSpace($evaluationAfter)) {
        throw 'STOP: evaluate returned no Last Evaluated At value.'
    }

    if (
        -not [string]::IsNullOrWhiteSpace($evaluationBefore) -and
        $evaluationAfter -eq $evaluationBefore
    ) {
        throw 'STOP: evaluate did not advance Last Evaluated At.'
    }
}

Write-Host ''
Write-Host ('=' * 72) -ForegroundColor Green
Write-Host 'PASS: CONTROLLED PACKAGING QUOTE ACTION EXECUTED' -ForegroundColor Green
Write-Host "Quote          : $QuoteNo" -ForegroundColor Green
Write-Host "Action         : $Action" -ForegroundColor Green
Write-Host "Resulting state: $($afterQuote.status)" -ForegroundColor Green
Write-Host ('=' * 72) -ForegroundColor Green