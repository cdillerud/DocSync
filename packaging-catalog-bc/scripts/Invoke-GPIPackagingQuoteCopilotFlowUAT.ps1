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

if (-not (Test-Path $PrepareScript)) {
    throw "STOP: 0.38 preparation component not found: $PrepareScript"
}

if (-not (Test-Path $ExecutorScript)) {
    throw "STOP: 0.37 execution component not found: $ExecutorScript"
}

# ------------------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------------------
function New-ConfirmationToken {
    param(
        [Parameter(Mandatory)]
        $Preparation
    )

    $material =
        @(
            'gpi-packaging-quote-action'
            [string]$Preparation.quoteId
            [string]$Preparation.quoteNo
            [string]$Preparation.currentStatus
            [string]$Preparation.requestedAction
            [string]$Preparation.contractVersion
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

$token =
    New-ConfirmationToken `
        -Preparation $preparation

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
                [bool]$preparation.isAllowed

            confirmationRequired =
                [bool]$preparation.confirmationRequired

            confirmationText =
                $preparation.confirmationText

            expectedResultStatus =
                $preparation.expectedResultStatus

            reason =
                $preparation.reason

            confirmationToken =
                if (
                    $preparation.isAllowed -and
                    $preparation.confirmationRequired
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

            writeExecution =
                [pscustomobject][ordered]@{
                    permitted =
                        [bool](
                            $preparation.isAllowed -and
                            $preparation.confirmationRequired
                        )

                    executeMode =
                        'Execute'

                    confirmationTokenRequired =
                        [bool](
                            $preparation.isAllowed -and
                            $preparation.confirmationRequired
                        )
                }
        }

    Write-FlowResult -Result $result
    return
}

# ------------------------------------------------------------------------
# EXECUTE MODE
# ------------------------------------------------------------------------
if (-not $preparation.isAllowed) {
    throw (
        "STOP: action '$Action' is not currently allowed for " +
        "Packaging Quote $QuoteNo. " +
        "Reason: $($preparation.reason)"
    )
}

if (-not $preparation.confirmationRequired) {
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
# DELEGATE THE ACTUAL WRITE TO 0.37
# 0.37 performs its own live contract revalidation before POST.
# ------------------------------------------------------------------------
& $ExecutorScript `
    -QuoteNo $QuoteNo `
    -Action $Action `
    -Confirmed `
    -TenantId $TenantId `
    -EnvironmentName $EnvironmentName `
    -CompanyId $CompanyId

if (-not $?) {
    throw 'STOP: 0.37 executor reported failure.'
}

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
            $preparation.expectedResultStatus

        resultingAllowedWriteActions =
            @($postPreparation.allowedWriteActions)

        recommendedNextAction =
            [string]$postPreparation.recommendedNextAction

        contractVersion =
            [string]$postPreparation.contractVersion
    }

Write-FlowResult -Result $result