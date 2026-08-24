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

    [ValidateSet('Object', 'Json')]
    [string]$OutputFormat = 'Json',

    [string]$TenantId =
        'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc',

    [string]$EnvironmentName =
        'Sandbox_NoZetadocs_UAT',

    [string]$CompanyId =
        '7d84c6d5-81e2-eb11-86df-00224822baa7'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ------------------------------------------------------------------------
# HARD SAFETY BOUNDARIES
# ------------------------------------------------------------------------
if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "STOP: this preparation utility is UAT-only. Environment received: $EnvironmentName"
}

if ($QuoteNo -eq 67) {
    throw 'STOP: Packaging Quote 67 is protected and may not be used by this utility.'
}

if (-not (Get-Command Get-AzAccessToken -ErrorAction SilentlyContinue)) {
    throw 'Get-AzAccessToken is not available. Connect with Az.Accounts first.'
}

# ------------------------------------------------------------------------
# AUTHENTICATION
# ------------------------------------------------------------------------
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

# ------------------------------------------------------------------------
# LIVE 0.36 SUMMARY CONTRACT
# ------------------------------------------------------------------------
$baseUri =
    "https://api.businesscentral.dynamics.com/v2.0/" +
    "$TenantId/$EnvironmentName/api/gpi/packagingQuotes/v1.0/" +
    "companies($CompanyId)"

$filter =
    [uri]::EscapeDataString(
        "entryNo eq $QuoteNo"
    )

$select = @(
    'id',
    'entryNo',
    'status',
    'customerNo',
    'customerName',
    'description',
    'lineCount',
    'approvalLineCount',
    'hasPricingExceptions',
    'decisionNoteRequired',
    'primaryPricingExceptionStatus',
    'primaryPricingExceptionMessage',
    'primaryApprover',
    'decisionNote',
    'readyForCustomerPresentation',
    'customerEmailReady',
    'actionContractVersion',
    'actionResource',
    'fullQuoteExpandName',
    'canEvaluate',
    'canMoveToReadyForReview',
    'canApprove',
    'canReject',
    'canReopen',
    'rejectDecisionNoteRequired',
    'allowedWriteActions',
    'writeConfirmationRequired',
    'actionContractNote',
    'recommendedNextAction'
) -join ','

$summaryUri =
    "$baseUri/packagingQuoteSummaries" +
    "?`$filter=$filter&`$select=$select"

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

$summary = $rows[0]

# ------------------------------------------------------------------------
# CONTRACT VALIDATION
# ------------------------------------------------------------------------
if ([string]$summary.actionContractVersion -ne '1.0') {
    throw "STOP: unsupported action contract version: $($summary.actionContractVersion)"
}

if ([string]$summary.actionResource -ne 'packagingQuotes') {
    throw "STOP: unexpected action resource: $($summary.actionResource)"
}

$allowedActions =
    @(
        @(
            ([string]$summary.allowedWriteActions).Split(
                ',',
                [System.StringSplitOptions]::RemoveEmptyEntries
            )
        ) |
        ForEach-Object {
            $_.Trim()
        }
    )

$isAllowed =
    $Action -in $allowedActions

# ------------------------------------------------------------------------
# EXPECTED RESULT
# ------------------------------------------------------------------------
$expectedResultStatus =
    switch ($Action) {
        'evaluate' {
            [string]$summary.status
        }

        'readyForReview' {
            'Ready'
        }

        'approve' {
            'Approved'
        }

        'reject' {
            'Rejected'
        }

        'reopen' {
            'Draft'
        }

        default {
            $null
        }
    }

# ------------------------------------------------------------------------
# DETERMINISTIC CONFIRMATION TEXT
# ------------------------------------------------------------------------
$confirmationText =
    switch ($Action) {
        'evaluate' {
            "Evaluate Packaging Quote $QuoteNo using the current Business Central pricing and guardrail rules?"
        }

        'readyForReview' {
            "Move Packaging Quote $QuoteNo to Ready for Review?"
        }

        'approve' {
            "Approve Packaging Quote ${QuoteNo}?"
        }

        'reject' {
            "Reject Packaging Quote ${QuoteNo}?"
        }

        'reopen' {
            "Reopen Packaging Quote $QuoteNo and return it to Draft?"
        }

        default {
            "Execute '$Action' for Packaging Quote ${QuoteNo}?"
        }
    }

# ------------------------------------------------------------------------
# DETERMINISTIC PREPARATION RESULT
# ------------------------------------------------------------------------
$reason = $null

if (-not $isAllowed) {
    if ($allowedActions.Count -eq 0) {
        $reason =
            "Action '$Action' is not currently permitted. " +
            "Business Central exposes no write actions for the quote in its current state."
    }
    else {
        $reason =
            "Action '$Action' is not currently permitted. " +
            "Allowed actions: " +
            ($allowedActions -join ', ') +
            '.'
    }
}
elseif ($summary.writeConfirmationRequired -ne $true) {
    $reason =
        "Action '$Action' is advertised as available, but the Business Central contract does not require write confirmation. Execution is therefore blocked by the orchestrator safety policy."

    $isAllowed = $false
}

$confirmationRequired =
    $isAllowed -and
    ($summary.writeConfirmationRequired -eq $true)

$payload = [ordered]@{
    schemaVersion = '1.0'

    environment = $EnvironmentName

    quoteNo = [int]$summary.entryNo
    quoteId = [string]$summary.id

    customerNo = [string]$summary.customerNo
    customerName = [string]$summary.customerName
    description = [string]$summary.description

    currentStatus = [string]$summary.status
    requestedAction = $Action

    isAllowed = [bool]$isAllowed
    confirmationRequired = [bool]$confirmationRequired

    confirmationText =
        if ($confirmationRequired) {
            $confirmationText
        }
        else {
            $null
        }

    expectedResultStatus =
        if ($isAllowed) {
            $expectedResultStatus
        }
        else {
            $null
        }

    reason = $reason

    allowedWriteActions = @($allowedActions)

    contractVersion =
        [string]$summary.actionContractVersion

    actionResource =
        [string]$summary.actionResource

    fullQuoteExpandName =
        [string]$summary.fullQuoteExpandName

    actionContractNote =
        [string]$summary.actionContractNote

    recommendedNextAction =
        [string]$summary.recommendedNextAction

    hasPricingExceptions =
        [bool]$summary.hasPricingExceptions

    approvalLineCount =
        [int]$summary.approvalLineCount

    decisionNoteRequired =
        [bool]$summary.decisionNoteRequired

    rejectDecisionNoteRequired =
        [bool]$summary.rejectDecisionNoteRequired

    primaryPricingExceptionStatus =
        [string]$summary.primaryPricingExceptionStatus

    primaryPricingExceptionMessage =
        [string]$summary.primaryPricingExceptionMessage

    primaryApprover =
        [string]$summary.primaryApprover

    readyForCustomerPresentation =
        [bool]$summary.readyForCustomerPresentation

    customerEmailReady =
        [bool]$summary.customerEmailReady

    writeExecution = [ordered]@{
        executor =
            'Invoke-GPIPackagingQuoteActionUAT.ps1'

        quoteNo =
            [int]$summary.entryNo

        action =
            $Action

        confirmationSwitch =
            '-Confirmed'

        mayExecute =
            [bool]$confirmationRequired
    }
}

$result =
    [pscustomobject]$payload

if ($OutputFormat -eq 'Object') {
    $result
}
else {
    $result |
        ConvertTo-Json `
            -Depth 8
}