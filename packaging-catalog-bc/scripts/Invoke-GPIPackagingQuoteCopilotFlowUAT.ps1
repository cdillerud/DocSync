[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Prepare', 'Execute')]
    [string]$Mode,

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

    [string]$ConfirmationToken,

    [string]$DecisionNote,

    [switch]$DecisionNoteAlreadyWritten,

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
# SAFETY BOUNDARIES
# ------------------------------------------------------------------------
if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "STOP: this Copilot flow is UAT-only. Environment received: $EnvironmentName"
}

if ($QuoteNo -eq 67) {
    throw 'STOP: Packaging Quote 67 is protected and may not be used by this flow.'
}

$ScriptRoot =
    Split-Path -Parent $MyInvocation.MyCommand.Path

$PrepareScript =
    Join-Path $ScriptRoot 'Prepare-GPIPackagingQuoteActionUAT.ps1'

$ExecutorScript =
    Join-Path $ScriptRoot 'Invoke-GPIPackagingQuoteActionUAT.ps1'

$DecisionNoteScript =
    Join-Path $ScriptRoot 'Set-GPIPackagingQuoteDecisionNoteUAT.ps1'

if (-not (Test-Path $PrepareScript)) {
    throw "STOP: 0.38 preparation component not found: $PrepareScript"
}

if (-not (Test-Path $ExecutorScript)) {
    throw "STOP: 0.37 execution component not found: $ExecutorScript"
}

if (-not (Test-Path $DecisionNoteScript)) {
    throw "STOP: 0.43 decision-note component not found: $DecisionNoteScript"
}

# ------------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------------
function New-ConfirmationToken {
    param(
        [Parameter(Mandatory)]
        $Preparation,

        [string]$DecisionNoteText = ''
    )

    $material =
        @(
            'gpi-packaging-quote-action'
            [string]$Preparation.quoteId
            [string]$Preparation.quoteNo
            [string]$Preparation.currentStatus
            [string]$Preparation.requestedAction
            [string]$Preparation.contractVersion
            [string]$DecisionNoteText
        ) -join '|'

    $bytes =
        [System.Text.Encoding]::UTF8.GetBytes($material)

    $sha =
        [System.Security.Cryptography.SHA256]::Create()

    try {
        $hashBytes =
            $sha.ComputeHash($bytes)
    }
    finally {
        $sha.Dispose()
    }

    $hash =
        [System.BitConverter]::ToString($hashBytes).
            Replace('-', '').
            ToLowerInvariant()

    $actionLabel =
        ([string]$Preparation.requestedAction).
            ToUpperInvariant()

    return (
        'GPI-Q{0}-{1}-{2}' -f
        $Preparation.quoteNo,
        $actionLabel,
        $hash.Substring(0, 24)
    )
}

function Get-LivePreparation {
    $result =
        & $PrepareScript `
            -QuoteNo $QuoteNo `
            -Action $Action `
            -OutputFormat Object `
            -TenantId $TenantId `
            -EnvironmentName $EnvironmentName `
            -CompanyId $CompanyId

    if ($null -eq $result) {
        throw 'STOP: preparation component returned no result.'
    }

    return $result
}

function Write-FlowResult {
    param(
        [Parameter(Mandatory)]
        $Result
    )

    if ($OutputFormat -eq 'Object') {
        $Result
    }
    else {
        $Result |
            ConvertTo-Json `
                -Depth 10
    }
}

# ------------------------------------------------------------------------
# ALWAYS PREPARE FROM LIVE BC STATE
# ------------------------------------------------------------------------
$preparation =
    Get-LivePreparation

$decisionNoteProvided =
    $PSBoundParameters.ContainsKey('DecisionNote')

$normalizedDecisionNote =
    if ($decisionNoteProvided) {
        ([string]$DecisionNote).Trim()
    }
    else {
        ''
    }

if (
    $decisionNoteProvided -and
    ($Action -notin @('approve', 'reject'))
) {
    throw (
        "STOP: DecisionNote may only be supplied with " +
        "approve or reject."
    )
}

if (
    $decisionNoteProvided -and
    [string]::IsNullOrWhiteSpace($normalizedDecisionNote)
) {
    throw 'STOP: supplied DecisionNote may not be blank.'
}

if ($normalizedDecisionNote -match '[\r\n]') {
    throw 'STOP: DecisionNote must be a single line.'
}

if (
    $DecisionNoteAlreadyWritten -and
    $Mode -ne 'Execute'
) {
    throw (
        'STOP: DecisionNoteAlreadyWritten is valid only ' +
        'in Execute mode.'
    )
}

if (
    $DecisionNoteAlreadyWritten -and
    -not $decisionNoteProvided
) {
    throw (
        'STOP: DecisionNoteAlreadyWritten requires ' +
        'DecisionNote.'
    )
}

$decisionNoteRequiredForAction =
    switch ($Action) {
        'approve' {
            [bool]$preparation.decisionNoteRequired
        }

        'reject' {
            [bool]$preparation.rejectDecisionNoteRequired
        }

        default {
            $false
        }
    }

$decisionNoteCanEnableAction =
    (-not [bool]$preparation.isAllowed) -and
    ([string]$preparation.currentStatus -eq 'Ready') -and
    ($Action -in @('approve', 'reject')) -and
    $decisionNoteRequiredForAction -and
    $decisionNoteProvided

$effectiveIsAllowed =
    [bool]$preparation.isAllowed -or
    $decisionNoteCanEnableAction

$effectiveConfirmationRequired =
    [bool]$effectiveIsAllowed

$effectiveReason =
    if ($decisionNoteCanEnableAction) {
        $null
    }
    else {
        $preparation.reason
    }

$decisionNoteWillBeWritten =
    $decisionNoteProvided -and
    ($Action -in @('approve', 'reject'))

$effectiveExpectedResultStatus =
    if ($effectiveIsAllowed) {
        switch ($Action) {
            'evaluate'       { [string]$preparation.currentStatus }
            'readyForReview' { 'Ready' }
            'approve'        { 'Approved' }
            'reject'         { 'Rejected' }
            'reopen'         { 'Draft' }
        }
    }
    else {
        $null
    }

$effectiveConfirmationText =
    if ($effectiveConfirmationRequired) {
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
        }
    }
    else {
        $null
    }

$token =
    New-ConfirmationToken `
        -Preparation $preparation `
        -DecisionNoteText $normalizedDecisionNote

# ------------------------------------------------------------------------
# PREPARE MODE
# ------------------------------------------------------------------------
if ($Mode -eq 'Prepare') {
    $result =
        [pscustomobject][ordered]@{
            schemaVersion = '1.0'
            mode = 'Prepare'

            quoteNo =
                [int]$preparation.quoteNo

            quoteId =
                [string]$preparation.quoteId

            customerNo =
                [string]$preparation.customerNo

            customerName =
                [string]$preparation.customerName

            currentStatus =
                [string]$preparation.currentStatus

            requestedAction =
                [string]$preparation.requestedAction

            isAllowed =
                [bool]$effectiveIsAllowed

            confirmationRequired =
                [bool]$effectiveConfirmationRequired

            confirmationText =
                $effectiveConfirmationText

            expectedResultStatus =
                $effectiveExpectedResultStatus

            reason =
                $effectiveReason

            confirmationToken =
                if (
                    $effectiveIsAllowed -and
                    $effectiveConfirmationRequired
                ) {
                    $token
                }
                else {
                    $null
                }

            allowedWriteActions =
                @($preparation.allowedWriteActions)

            contractVersion =
                [string]$preparation.contractVersion

            recommendedNextAction =
                [string]$preparation.recommendedNextAction

            hasPricingExceptions =
                [bool]$preparation.hasPricingExceptions

            primaryPricingExceptionStatus =
                [string]$preparation.primaryPricingExceptionStatus

            primaryPricingExceptionMessage =
                [string]$preparation.primaryPricingExceptionMessage

            primaryApprover =
                [string]$preparation.primaryApprover

            decisionNoteRequired =
                [bool]$decisionNoteRequiredForAction

            decisionNoteProvided =
                [bool]$decisionNoteProvided

            decisionNote =
                if ($decisionNoteProvided) {
                    $normalizedDecisionNote
                }
                else {
                    $null
                }

            decisionNoteWillBeWritten =
                [bool]$decisionNoteWillBeWritten

            decisionNoteEnablesAction =
                [bool]$decisionNoteCanEnableAction

            writeExecution =
                [pscustomobject][ordered]@{
                    permitted =
                        [bool](
                            $effectiveIsAllowed -and
                            $effectiveConfirmationRequired
                        )

                    executeMode =
                        'Execute'

                    confirmationTokenRequired =
                        [bool](
                            $effectiveIsAllowed -and
                            $effectiveConfirmationRequired
                        )
                }
        }

    Write-FlowResult -Result $result
    return
}

# ------------------------------------------------------------------------
# EXECUTE MODE
# ------------------------------------------------------------------------
if (-not $effectiveIsAllowed) {
    throw (
        "STOP: action '$Action' is not currently allowed for " +
        "Packaging Quote $QuoteNo. " +
        "Reason: $effectiveReason"
    )
}

if (-not $effectiveConfirmationRequired) {
    throw (
        "STOP: live preparation does not require explicit confirmation. " +
        "Execution is blocked by the 0.39 safety policy."
    )
}

if ([string]::IsNullOrWhiteSpace($ConfirmationToken)) {
    throw (
        "STOP: Execute mode requires the confirmation token returned " +
        "by Prepare mode."
    )
}

if (
    -not [string]::Equals(
        $ConfirmationToken,
        $token,
        [System.StringComparison]::Ordinal
    )
) {
    throw (
        "STOP: confirmation token does not match the current live " +
        "quote/action state. Prepare the action again before executing."
    )
}

# ------------------------------------------------------------------------
# OPTIONAL CONTROLLED DECISION-NOTE WRITE
# ------------------------------------------------------------------------
if (
    $decisionNoteWillBeWritten -and
    -not $DecisionNoteAlreadyWritten
) {
    $decisionNoteOutput =
        & $DecisionNoteScript `
            -QuoteNo $QuoteNo `
            -DecisionNote $normalizedDecisionNote `
            -Confirmed `
            -TenantId $TenantId `
            -EnvironmentName $EnvironmentName `
            -CompanyId $CompanyId
}

if ($decisionNoteWillBeWritten) {
    $postNotePreparation =
        Get-LivePreparation

    if (-not [bool]$postNotePreparation.isAllowed) {
        throw (
            "STOP: decision note is present, but action '$Action' " +
            "is still not permitted. Reason: $($postNotePreparation.reason)"
        )
    }
}

# ------------------------------------------------------------------------
# DELEGATE THE ACTUAL WRITE TO 0.37
# 0.37 performs its own live contract revalidation before POST.
# ------------------------------------------------------------------------
$executorOutput =
    & $ExecutorScript `
        -QuoteNo $QuoteNo `
        -Action $Action `
        -Confirmed `
        -TenantId $TenantId `
        -EnvironmentName $EnvironmentName `
        -CompanyId $CompanyId

# ------------------------------------------------------------------------
# READ FRESH POST-EXECUTION STATE
# ------------------------------------------------------------------------
$postPreparation =
    Get-LivePreparation

$result =
    [pscustomobject][ordered]@{
        schemaVersion = '1.0'
        mode = 'Execute'

        quoteNo =
            [int]$postPreparation.quoteNo

        quoteId =
            [string]$postPreparation.quoteId

        requestedAction =
            $Action

        executed =
            $true

        statusBefore =
            [string]$preparation.currentStatus

        statusAfter =
            [string]$postPreparation.currentStatus

        expectedResultStatus =
            $effectiveExpectedResultStatus

        decisionNoteWritten =
            [bool]$decisionNoteWillBeWritten

        decisionNote =
            if ($decisionNoteWillBeWritten) {
                $normalizedDecisionNote
            }
            else {
                $null
            }

        resultingAllowedWriteActions =
            @($postPreparation.allowedWriteActions)

        recommendedNextAction =
            [string]$postPreparation.recommendedNextAction

        contractVersion =
            [string]$postPreparation.contractVersion
    }

Write-FlowResult -Result $result