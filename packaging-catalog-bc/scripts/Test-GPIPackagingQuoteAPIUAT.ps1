[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$ProductNo = "TEST-12OZ-001",
    [string]$ExpectedBCItemNo = "20041936-P4305"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$CreatedQuoteIds = [System.Collections.Generic.List[string]]::new()
$CreatedRuleIds = [System.Collections.Generic.List[string]]::new()
$Results = [System.Collections.Generic.List[object]]::new()
$RunId = "QUOTE-API-UAT-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$Token = $null
$Secret = $null
$CompanyId = $null
$QuoteBase = $null
$UatBase = $null

function ConvertFrom-BcEnum {
    param([AllowNull()][string]$Value)

    if ($null -eq $Value) {
        return ""
    }

    return $Value.Replace("_x0020_", " ").Replace("_x002D_", "-").Trim()
}

function Add-TestResult {
    param(
        [Parameter(Mandatory)][string]$Scenario,
        [Parameter(Mandatory)][string]$Check,
        [Parameter(Mandatory)][bool]$Passed,
        [AllowNull()]$Actual,
        [AllowNull()]$Expected
    )

    $Results.Add([pscustomobject]@{
        Scenario = $Scenario
        Check = $Check
        Passed = $Passed
        Actual = [string]$Actual
        Expected = [string]$Expected
    }) | Out-Null
}

function Assert-Equal {
    param(
        [string]$Scenario,
        [string]$Check,
        $Actual,
        $Expected
    )

    $passed = ([string]$Actual -eq [string]$Expected)
    Add-TestResult -Scenario $Scenario -Check $Check -Passed $passed -Actual $Actual -Expected $Expected
}

function Assert-DecimalNear {
    param(
        [string]$Scenario,
        [string]$Check,
        [decimal]$Actual,
        [decimal]$Expected,
        [decimal]$Tolerance = 0.0001
    )

    $passed = ([math]::Abs([double]($Actual - $Expected)) -le [double]$Tolerance)
    Add-TestResult -Scenario $Scenario -Check $Check -Passed $passed -Actual $Actual -Expected "$Expected +/- $Tolerance"
}

function Assert-NotBlank {
    param(
        [string]$Scenario,
        [string]$Check,
        [AllowNull()]$Actual
    )

    $passed = -not [string]::IsNullOrWhiteSpace([string]$Actual)
    Add-TestResult -Scenario $Scenario -Check $Check -Passed $passed -Actual $Actual -Expected "nonblank"
}

function Get-ErrorBody {
    param([System.Management.Automation.ErrorRecord]$ErrorRecord)

    try {
        if ($ErrorRecord.Exception.Response -and $ErrorRecord.Exception.Response.Content) {
            return $ErrorRecord.Exception.Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        }
    }
    catch {
    }

    return $ErrorRecord.Exception.Message
}

function Invoke-BcRequest {
    param(
        [Parameter(Mandatory)][ValidateSet("GET", "POST", "PATCH", "DELETE")][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [AllowNull()]$Body,
        [switch]$IfMatch
    )

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = "application/json"
    }

    if ($IfMatch) {
        $headers["If-Match"] = "*"
    }

    try {
        if ($null -eq $Body) {
            return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers
        }

        $json = $Body | ConvertTo-Json -Depth 10 -Compress
        return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -ContentType "application/json" -Body $json
    }
    catch {
        $detail = Get-ErrorBody -ErrorRecord $_
        throw "Business Central API $Method failed: $Uri`n$detail"
    }
}

function Test-BcRequestFails {
    param(
        [Parameter(Mandatory)][ValidateSet("POST", "PATCH", "DELETE")][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [AllowNull()]$Body,
        [switch]$IfMatch
    )

    try {
        $null = Invoke-BcRequest -Method $Method -Uri $Uri -Body $Body -IfMatch:$IfMatch
        return $false
    }
    catch {
        return $true
    }
}

function New-QuoteScenario {
    param(
        [Parameter(Mandatory)][string]$Scenario,
        [Parameter(Mandatory)][string]$CustomerNo,
        [Parameter(Mandatory)][decimal]$LandedCost,
        [Parameter(Mandatory)][decimal]$ProposedSell,
        [Parameter(Mandatory)][decimal]$TargetMargin
    )

    $quote = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuotes" -Body @{
        quoteDate = (Get-Date).ToString("yyyy-MM-dd")
        customerNo = $CustomerNo
        description = "$RunId $Scenario"
    }

    $CreatedQuoteIds.Add([string]$quote.id) | Out-Null

    $line = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuoteLines" -Body @{
        quoteEntryNo = [int]$quote.entryNo
        productNo = $ProductNo
        quantity = 1
        landedCostPerUnit = $LandedCost
        proposedSellPrice = $ProposedSell
        targetGrossMarginPct = $TargetMargin
    }

    return [pscustomobject]@{
        Quote = $quote
        Line = $line
    }
}

function Invoke-EvaluateQuote {
    param([Parameter(Mandatory)][string]$QuoteId)
    $null = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuotes($QuoteId)/Microsoft.NAV.evaluate" -Body @{}
}

function Invoke-ReadyForReview {
    param([Parameter(Mandatory)][string]$QuoteId)
    $null = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuotes($QuoteId)/Microsoft.NAV.readyForReview" -Body @{}
}

function Invoke-ApproveQuote {
    param([Parameter(Mandatory)][string]$QuoteId)
    $null = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuotes($QuoteId)/Microsoft.NAV.approve" -Body @{}
}

function Invoke-RejectQuote {
    param([Parameter(Mandatory)][string]$QuoteId)
    $null = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuotes($QuoteId)/Microsoft.NAV.reject" -Body @{}
}

function Invoke-ReopenQuote {
    param([Parameter(Mandatory)][string]$QuoteId)
    $null = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuotes($QuoteId)/Microsoft.NAV.reopen" -Body @{}
}

function Get-Quote {
    param([Parameter(Mandatory)][string]$QuoteId)
    return Invoke-BcRequest -Method GET -Uri "$QuoteBase/packagingQuotes($QuoteId)" -Body $null
}

function Get-QuoteLine {
    param([Parameter(Mandatory)][string]$LineId)
    return Invoke-BcRequest -Method GET -Uri "$QuoteBase/packagingQuoteLines($LineId)" -Body $null
}

function Get-QuoteAudits {
    param([Parameter(Mandatory)][int]$QuoteEntryNo)

    $filterText = [uri]::EscapeDataString("quoteEntryNo eq $QuoteEntryNo")
    $response = Invoke-BcRequest -Method GET -Uri "$QuoteBase/packagingQuoteAudits?`$filter=$filterText" -Body $null
    return @($response.value)
}

function New-UatFixedRule {
    param(
        [Parameter(Mandatory)][string]$CustomerNo,
        [Parameter(Mandatory)][decimal]$LockedPrice
    )

    $lastError = $null
    foreach ($ruleType in @("Fixed_x0020_Price", "Fixed Price")) {
        try {
            $rule = Invoke-BcRequest -Method POST -Uri "$UatBase/pricingGuardrailsUAT" -Body @{
                enabled = $true
                customerNo = $CustomerNo
                itemNo = $ExpectedBCItemNo
                ruleType = $ruleType
                lockedSellPrice = $LockedPrice
                approver = "TEST ONLY"
                notes = $RunId
            }

            $CreatedRuleIds.Add([string]$rule.id) | Out-Null
            return $rule
        }
        catch {
            $lastError = $_
        }
    }

    throw $lastError
}

try {
    Write-Host ""
    Write-Host "GPI PACKAGING QUOTE API UAT" -ForegroundColor Cyan
    Write-Host "Run ID      : $RunId"
    Write-Host "Environment : $EnvironmentName"
    Write-Host "Product     : $ProductNo"
    Write-Host "BC Item     : $ExpectedBCItemNo"
    Write-Host ""

    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        throw "Azure CLI (az) is required."
    }

    $accountJson = & az account show --output json --only-show-errors 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($accountJson | Out-String))) {
        & az login --tenant $TenantId --only-show-errors | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Azure login failed."
        }
    }

    $Secret = (& az keyvault secret show --vault-name $KeyVaultName --name "bc-client-secret" --query value --output tsv --only-show-errors).Trim()
    if ([string]::IsNullOrWhiteSpace($Secret)) {
        throw "Could not retrieve bc-client-secret from Key Vault $KeyVaultName."
    }

    $tokenResponse = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType "application/x-www-form-urlencoded" -Body @{
        grant_type = "client_credentials"
        client_id = $ClientId
        client_secret = $Secret
        scope = "https://api.businesscentral.dynamics.com/.default"
    }
    $Token = [string]$tokenResponse.access_token
    if ([string]::IsNullOrWhiteSpace($Token)) {
        throw "Microsoft identity platform did not return an access token."
    }

    $bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
    $companies = Invoke-BcRequest -Method GET -Uri "$bcBase/api/v2.0/companies" -Body $null
    $company = @($companies.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
    if (-not $company) {
        throw "Company '$CompanyName' was not returned by the Business Central API."
    }

    $CompanyId = [string]$company.id
    $QuoteBase = "$bcBase/api/gpi/packagingQuotes/v1.0/companies($CompanyId)"
    $UatBase = "$bcBase/api/gpi/packagingQuoteUAT/v1.0/companies($CompanyId)"

    Write-Host "Company ID  : $CompanyId"
    Write-Host ""

    # 1. Special Pricing, Ready for Review, approval-note enforcement, approval snapshot, decision lock, and reopen.
    $scenario = "Special Pricing"
    $s = New-QuoteScenario -Scenario $scenario -CustomerNo "TRIPLEH" -LandedCost 168.44 -ProposedSell 224.81 -TargetMargin 25
    Invoke-EvaluateQuote -QuoteId $s.Quote.id
    $line = Get-QuoteLine -LineId $s.Line.id
    Assert-Equal $scenario "BC item mapping" $line.bcItemNo $ExpectedBCItemNo
    Assert-Equal $scenario "Guardrail status" (ConvertFrom-BcEnum $line.guardrailStatus) "Special Pricing"
    Assert-Equal $scenario "Needs approval" $line.needsApproval $true
    Assert-Equal $scenario "Approver" $line.guardrailApprover "TEST ONLY"
    Assert-DecimalNear $scenario "Calculated GP %" ([decimal]$line.calculatedGrossMarginPct) 25.07451 0.0001

    Invoke-ReadyForReview -QuoteId $s.Quote.id
    $quote = Get-Quote -QuoteId $s.Quote.id
    Assert-Equal $scenario "Ready for Review transition" (ConvertFrom-BcEnum $quote.status) "Ready"

    $approvalWithoutNoteBlocked = Test-BcRequestFails -Method POST -Uri "$QuoteBase/packagingQuotes($($s.Quote.id))/Microsoft.NAV.approve" -Body @{}
    Assert-Equal $scenario "Pricing exception approval requires note" $approvalWithoutNoteBlocked $true

    $approvalNote = "$RunId Special Pricing approved for UAT"
    $null = Invoke-BcRequest -Method PATCH -Uri "$QuoteBase/packagingQuotes($($s.Quote.id))" -IfMatch -Body @{
        decisionNote = $approvalNote
    }
    Invoke-ApproveQuote -QuoteId $s.Quote.id
    $quote = Get-Quote -QuoteId $s.Quote.id
    Assert-Equal $scenario "Approved status" (ConvertFrom-BcEnum $quote.status) "Approved"
    Assert-Equal $scenario "Decision note retained" $quote.decisionNote $approvalNote
    Assert-NotBlank $scenario "Decision timestamp" $quote.decisionAt
    Assert-NotBlank $scenario "Decision user" $quote.decisionBy

    $audits = Get-QuoteAudits -QuoteEntryNo ([int]$s.Quote.entryNo)
    $approvedHeaderAudit = @($audits | Where-Object { (ConvertFrom-BcEnum $_.eventType) -eq "Approved" -and [int]$_.lineNo -eq 0 }) | Select-Object -First 1
    $approvedLineAudit = @($audits | Where-Object { (ConvertFrom-BcEnum $_.eventType) -eq "Approved" -and [int]$_.lineNo -gt 0 }) | Select-Object -First 1
    Assert-Equal $scenario "Approved header audit exists" ($null -ne $approvedHeaderAudit) $true
    Assert-Equal $scenario "Approved line snapshot exists" ($null -ne $approvedLineAudit) $true
    if ($approvedLineAudit) {
        Assert-DecimalNear $scenario "Approved audit sell snapshot" ([decimal]$approvedLineAudit.proposedSellPrice) 224.81 0.0001
        Assert-Equal $scenario "Approved audit guardrail" (ConvertFrom-BcEnum $approvedLineAudit.guardrailStatus) "Special Pricing"
        Assert-Equal $scenario "Approved audit decision note" $approvedLineAudit.decisionNote $approvalNote
    }

    $approvedEditBlocked = Test-BcRequestFails -Method PATCH -Uri "$QuoteBase/packagingQuoteLines($($s.Line.id))" -IfMatch -Body @{
        proposedSellPrice = 225
    }
    Assert-Equal $scenario "Approved pricing edit blocked" $approvedEditBlocked $true

    Invoke-ReopenQuote -QuoteId $s.Quote.id
    $quote = Get-Quote -QuoteId $s.Quote.id
    $line = Get-QuoteLine -LineId $s.Line.id
    Assert-Equal $scenario "Reopen returns Draft" (ConvertFrom-BcEnum $quote.status) "Draft"
    Assert-Equal $scenario "Reopen invalidates guardrail" (ConvertFrom-BcEnum $line.guardrailStatus) "Not Evaluated"
    $audits = Get-QuoteAudits -QuoteEntryNo ([int]$s.Quote.entryNo)
    $reopenAudit = @($audits | Where-Object { (ConvertFrom-BcEnum $_.eventType) -eq "Reopened" }) | Select-Object -First 1
    Assert-Equal $scenario "Reopen audit exists" ($null -ne $reopenAudit) $true

    # 2. Clean within-policy quote.
    $scenario = "Within Policy"
    $s = New-QuoteScenario -Scenario $scenario -CustomerNo "POPSPEP" -LandedCost 168.44 -ProposedSell 240 -TargetMargin 25
    Invoke-EvaluateQuote -QuoteId $s.Quote.id
    $line = Get-QuoteLine -LineId $s.Line.id
    Assert-Equal $scenario "Guardrail status" (ConvertFrom-BcEnum $line.guardrailStatus) "Within Policy"
    Assert-Equal $scenario "Needs approval" $line.needsApproval $false

    # 3. Below-target margin, pricing-change audit, and re-evaluation.
    $scenario = "Below Target Margin"
    $s = New-QuoteScenario -Scenario $scenario -CustomerNo "POPSPEP" -LandedCost 168.44 -ProposedSell 200 -TargetMargin 25
    Invoke-EvaluateQuote -QuoteId $s.Quote.id
    $line = Get-QuoteLine -LineId $s.Line.id
    Assert-Equal $scenario "Guardrail status" (ConvertFrom-BcEnum $line.guardrailStatus) "Below Target Margin"
    Assert-Equal $scenario "Needs approval" $line.needsApproval $true

    $null = Invoke-BcRequest -Method PATCH -Uri "$QuoteBase/packagingQuoteLines($($s.Line.id))" -IfMatch -Body @{
        proposedSellPrice = 240
    }
    $line = Get-QuoteLine -LineId $s.Line.id
    Assert-Equal $scenario "Pricing edit invalidates evaluation" (ConvertFrom-BcEnum $line.guardrailStatus) "Not Evaluated"

    $audits = Get-QuoteAudits -QuoteEntryNo ([int]$s.Quote.entryNo)
    $pricingAudit = @($audits | Where-Object { (ConvertFrom-BcEnum $_.eventType) -eq "Pricing Changed" -and [int]$_.lineNo -gt 0 }) | Select-Object -First 1
    Assert-Equal $scenario "Pricing change audit exists" ($null -ne $pricingAudit) $true
    if ($pricingAudit) {
        Assert-DecimalNear $scenario "Previous sell captured" ([decimal]$pricingAudit.previousSellPrice) 200 0.0001
        Assert-DecimalNear $scenario "New sell captured" ([decimal]$pricingAudit.proposedSellPrice) 240 0.0001
        Assert-Equal $scenario "Previous guardrail captured" (ConvertFrom-BcEnum $pricingAudit.previousGuardrailStatus) "Below Target Margin"
    }

    Invoke-EvaluateQuote -QuoteId $s.Quote.id
    $line = Get-QuoteLine -LineId $s.Line.id
    Assert-Equal $scenario "Re-evaluation after corrected sell" (ConvertFrom-BcEnum $line.guardrailStatus) "Within Policy"

    # 4. Missing landed cost is incomplete and requires approval.
    $scenario = "Missing Cost"
    $s = New-QuoteScenario -Scenario $scenario -CustomerNo "POPSPEP" -LandedCost 0 -ProposedSell 240 -TargetMargin 25
    Invoke-EvaluateQuote -QuoteId $s.Quote.id
    $line = Get-QuoteLine -LineId $s.Line.id
    Assert-Equal $scenario "Guardrail status" (ConvertFrom-BcEnum $line.guardrailStatus) "Missing Cost"
    Assert-Equal $scenario "Needs approval" $line.needsApproval $true

    # 5. Sandbox-only temporary Fixed Price rule, match and conflict, then rejection audit.
    $fixedCustomer = "ELDERBE"
    $null = New-UatFixedRule -CustomerNo $fixedCustomer -LockedPrice 250

    $scenario = "Fixed Price Match"
    $s = New-QuoteScenario -Scenario $scenario -CustomerNo $fixedCustomer -LandedCost 168.44 -ProposedSell 250 -TargetMargin 25
    Invoke-EvaluateQuote -QuoteId $s.Quote.id
    $line = Get-QuoteLine -LineId $s.Line.id
    Assert-Equal $scenario "Guardrail status" (ConvertFrom-BcEnum $line.guardrailStatus) "Fixed Price Match"
    Assert-Equal $scenario "Needs approval" $line.needsApproval $false
    Assert-DecimalNear $scenario "Policy fixed sell" ([decimal]$line.policyFixedSellPrice) 250 0.0001
    Assert-Equal $scenario "Approver" $line.guardrailApprover "TEST ONLY"

    $scenario = "Fixed Price Conflict"
    $s = New-QuoteScenario -Scenario $scenario -CustomerNo $fixedCustomer -LandedCost 168.44 -ProposedSell 245 -TargetMargin 25
    Invoke-EvaluateQuote -QuoteId $s.Quote.id
    $line = Get-QuoteLine -LineId $s.Line.id
    Assert-Equal $scenario "Guardrail status" (ConvertFrom-BcEnum $line.guardrailStatus) "Fixed Price Conflict"
    Assert-Equal $scenario "Needs approval" $line.needsApproval $true
    Assert-DecimalNear $scenario "Policy fixed sell" ([decimal]$line.policyFixedSellPrice) 250 0.0001
    Assert-Equal $scenario "Approver" $line.guardrailApprover "TEST ONLY"

    Invoke-ReadyForReview -QuoteId $s.Quote.id
    $rejectNote = "$RunId Fixed price conflict rejected for UAT"
    $null = Invoke-BcRequest -Method PATCH -Uri "$QuoteBase/packagingQuotes($($s.Quote.id))" -IfMatch -Body @{
        decisionNote = $rejectNote
    }
    Invoke-RejectQuote -QuoteId $s.Quote.id
    $quote = Get-Quote -QuoteId $s.Quote.id
    Assert-Equal $scenario "Rejected status" (ConvertFrom-BcEnum $quote.status) "Rejected"
    Assert-Equal $scenario "Rejection note retained" $quote.decisionNote $rejectNote
    Assert-NotBlank $scenario "Rejection timestamp" $quote.decisionAt
    Assert-NotBlank $scenario "Rejection user" $quote.decisionBy

    $audits = Get-QuoteAudits -QuoteEntryNo ([int]$s.Quote.entryNo)
    $rejectedLineAudit = @($audits | Where-Object { (ConvertFrom-BcEnum $_.eventType) -eq "Rejected" -and [int]$_.lineNo -gt 0 }) | Select-Object -First 1
    Assert-Equal $scenario "Rejected line snapshot exists" ($null -ne $rejectedLineAudit) $true
    if ($rejectedLineAudit) {
        Assert-DecimalNear $scenario "Rejected audit sell snapshot" ([decimal]$rejectedLineAudit.proposedSellPrice) 245 0.0001
        Assert-Equal $scenario "Rejected audit decision note" $rejectedLineAudit.decisionNote $rejectNote
    }

    $rejectedDecisionEditBlocked = Test-BcRequestFails -Method PATCH -Uri "$QuoteBase/packagingQuotes($($s.Quote.id))" -IfMatch -Body @{
        decisionNote = "changed after rejection"
    }
    Assert-Equal $scenario "Rejected decision note locked" $rejectedDecisionEditBlocked $true
}
finally {
    if ($QuoteBase) {
        foreach ($quoteId in $CreatedQuoteIds) {
            try {
                $null = Invoke-BcRequest -Method DELETE -Uri "$QuoteBase/packagingQuotes($quoteId)" -IfMatch -Body $null
            }
            catch {
                Write-Warning "Could not delete UAT quote $quoteId. $($_.Exception.Message)"
            }
        }
    }

    if ($UatBase) {
        foreach ($ruleId in $CreatedRuleIds) {
            try {
                $null = Invoke-BcRequest -Method DELETE -Uri "$UatBase/pricingGuardrailsUAT($ruleId)" -IfMatch -Body $null
            }
            catch {
                Write-Warning "Could not delete UAT pricing rule $ruleId. $($_.Exception.Message)"
            }
        }
    }

    $Secret = $null
    $Token = $null
}

Write-Host ""
Write-Host "UAT RESULTS" -ForegroundColor Cyan
$Results | Format-Table Scenario, Check, Passed, Actual, Expected -AutoSize

$failed = @($Results | Where-Object { -not $_.Passed })
Write-Host ""
Write-Host "Checks run : $($Results.Count)"
Write-Host "Passed     : $($Results.Count - $failed.Count)"
Write-Host "Failed     : $($failed.Count)"
Write-Host "Cleanup    : temporary quotes, audit rows, and fixed-price UAT rule removed"

if ($failed.Count -gt 0) {
    Write-Host "PACKAGING QUOTE API UAT FAILED" -ForegroundColor Red
    exit 1
}

Write-Host "PACKAGING QUOTE API UAT PASSED" -ForegroundColor Green
exit 0
