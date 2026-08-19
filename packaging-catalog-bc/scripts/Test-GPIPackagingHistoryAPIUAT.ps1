[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$ProductNo = "TEST-12OZ-001",
    [string]$ExpectedBCItemNo = "20041936-P4305",
    [string]$HistoryCustomerNo = "POPSPEP",
    [string]$HistoryUomCode = "M"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$CreatedQuoteIds = [System.Collections.Generic.List[string]]::new()
$Results = [System.Collections.Generic.List[object]]::new()
$RunId = "HISTORY-API-UAT-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$Token = $null
$Secret = $null
$QuoteBase = $null
$HistBase = $null

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
    param([string]$Scenario, [string]$Check, $Actual, $Expected)
    Add-TestResult -Scenario $Scenario -Check $Check -Passed ([string]$Actual -eq [string]$Expected) -Actual $Actual -Expected $Expected
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
    param([string]$Scenario, [string]$Check, [AllowNull()]$Actual)
    $passed = -not [string]::IsNullOrWhiteSpace([string]$Actual)
    Add-TestResult -Scenario $Scenario -Check $Check -Passed $passed -Actual $Actual -Expected "nonblank"
}

function Assert-GreaterOrEqual {
    param([string]$Scenario, [string]$Check, [decimal]$Actual, [decimal]$ExpectedMinimum)
    Add-TestResult -Scenario $Scenario -Check $Check -Passed ($Actual -ge $ExpectedMinimum) -Actual $Actual -Expected ">= $ExpectedMinimum"
}

function Assert-GreaterThanZero {
    param([string]$Scenario, [string]$Check, [decimal]$Actual)
    Add-TestResult -Scenario $Scenario -Check $Check -Passed ($Actual -gt 0) -Actual $Actual -Expected "> 0"
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

function Get-HistoricalSales {
    param(
        [AllowEmptyString()][string]$CustomerNo,
        [Parameter(Mandatory)][string]$ItemNo,
        [Parameter(Mandatory)][string]$UomCode,
        [Parameter(Mandatory)][datetime]$AsOfDate
    )

    $filterParts = [System.Collections.Generic.List[string]]::new()
    if (-not [string]::IsNullOrWhiteSpace($CustomerNo)) {
        $filterParts.Add("customerNo eq '$CustomerNo'") | Out-Null
    }
    $filterParts.Add("itemNo eq '$ItemNo'") | Out-Null
    $filterParts.Add("unitOfMeasureCode eq '$UomCode'") | Out-Null

    $filterText = [uri]::EscapeDataString(($filterParts -join " and "))
    $response = Invoke-BcRequest -Method GET -Uri "$HistBase/historicalSalesLines?`$filter=$filterText" -Body $null

    return @(
        $response.value |
            Where-Object {
                ([decimal]$_.quantity -gt 0) -and
                ([decimal]$_.unitPrice -gt 0) -and
                ([datetime]$_.postingDate -le $AsOfDate.Date.AddDays(1).AddTicks(-1))
            }
    )
}

function Get-RecentHistory {
    param([Parameter(Mandatory)][object[]]$Rows)

    return @(
        $Rows |
            Sort-Object `
                @{ Expression = { [datetime]$_.postingDate }; Descending = $true }, `
                @{ Expression = { [string]$_.invoiceNo }; Descending = $true }, `
                @{ Expression = { [int]$_.lineNo }; Descending = $true } |
            Select-Object -First 5
    )
}

function Get-Median {
    param([Parameter(Mandatory)][decimal[]]$Values)

    if ($Values.Count -eq 0) {
        return [decimal]0
    }

    $sorted = @($Values | Sort-Object)
    if (($sorted.Count % 2) -eq 1) {
        return [decimal]$sorted[[int](($sorted.Count - 1) / 2)]
    }

    $upper = [int]($sorted.Count / 2)
    $lower = $upper - 1
    return [decimal](($sorted[$lower] + $sorted[$upper]) / 2)
}

function New-HistoryQuote {
    param(
        [Parameter(Mandatory)][string]$Scenario,
        [Parameter(Mandatory)][decimal]$LandedCost,
        [Parameter(Mandatory)][decimal]$ProposedSell
    )

    $quote = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuotes" -Body @{
        quoteDate = (Get-Date).ToString("yyyy-MM-dd")
        customerNo = $HistoryCustomerNo
        description = "$RunId $Scenario"
    }
    $CreatedQuoteIds.Add([string]$quote.id) | Out-Null

    $line = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuoteLines" -Body @{
        quoteEntryNo = [int]$quote.entryNo
        productNo = $ProductNo
        quantity = 1
        landedCostPerUnit = $LandedCost
        proposedSellPrice = $ProposedSell
        targetGrossMarginPct = 0
    }

    $null = Invoke-BcRequest -Method PATCH -Uri "$QuoteBase/packagingQuoteLines($($line.id))" -IfMatch -Body @{
        uomCode = $HistoryUomCode
    }

    return [pscustomobject]@{
        Quote = $quote
        LineId = [string]$line.id
    }
}

function Invoke-EvaluateQuote {
    param([Parameter(Mandatory)][string]$QuoteId)
    $null = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuotes($QuoteId)/Microsoft.NAV.evaluate" -Body @{}
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

try {
    Write-Host ""
    Write-Host "GPI PACKAGING CUSTOMER HISTORY API UAT" -ForegroundColor Cyan
    Write-Host "Run ID      : $RunId"
    Write-Host "Environment : $EnvironmentName"
    Write-Host "Customer    : $HistoryCustomerNo"
    Write-Host "Product     : $ProductNo"
    Write-Host "BC Item     : $ExpectedBCItemNo"
    Write-Host "UOM         : $HistoryUomCode"
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

    $companyId = [string]$company.id
    $QuoteBase = "$bcBase/api/gpi/packagingQuotes/v1.0/companies($companyId)"
    $HistBase = "$bcBase/api/gpi/commercialGuardrails/v1.0/companies($companyId)"

    Write-Host "Company ID  : $companyId"
    Write-Host ""

    $asOfDate = (Get-Date).Date
    $customerHistory = Get-HistoricalSales -CustomerNo $HistoryCustomerNo -ItemNo $ExpectedBCItemNo -UomCode $HistoryUomCode -AsOfDate $asOfDate
    if ($customerHistory.Count -lt 3) {
        throw "History UAT requires at least 3 exact posted lines for $HistoryCustomerNo / $ExpectedBCItemNo / $HistoryUomCode. Found $($customerHistory.Count)."
    }

    $recentCustomerHistory = Get-RecentHistory -Rows $customerHistory
    $customerMedian = Get-Median -Values @($recentCustomerHistory | ForEach-Object { [decimal]$_.unitPrice })
    if ($customerMedian -le 0) {
        throw "Customer history median was not positive."
    }

    $allCustomerHistory = Get-HistoricalSales -CustomerNo "" -ItemNo $ExpectedBCItemNo -UomCode $HistoryUomCode -AsOfDate $asOfDate
    $recentAllCustomerHistory = Get-RecentHistory -Rows $allCustomerHistory
    $allCustomerMedian = Get-Median -Values @($recentAllCustomerHistory | ForEach-Object { [decimal]$_.unitPrice })

    $landedCost = [decimal][math]::Round([double]($customerMedian * [decimal]0.25), 5)
    if ($landedCost -le 0) {
        $landedCost = [decimal]0.01
    }

    $belowSell = [decimal][math]::Round([double]($customerMedian * [decimal]0.90), 5)
    $aboveSell = [decimal][math]::Round([double]($customerMedian * [decimal]1.20), 5)

    Write-Host "Exact customer history lines : $($customerHistory.Count)"
    Write-Host "Recent customer median       : $customerMedian"
    Write-Host "All-customer history lines   : $($allCustomerHistory.Count)"
    Write-Host "Recent all-customer median   : $allCustomerMedian"
    Write-Host ""

    $scenario = "Below Customer History"
    $s = New-HistoryQuote -Scenario $scenario -LandedCost $landedCost -ProposedSell $belowSell
    Invoke-EvaluateQuote -QuoteId $s.Quote.id
    $line = Get-QuoteLine -LineId $s.LineId

    Assert-Equal $scenario "Guardrail status" (ConvertFrom-BcEnum $line.guardrailStatus) "Below Customer History"
    Assert-Equal $scenario "Needs approval" $line.needsApproval $true
    Assert-Equal $scenario "Exact history line count" ([int]$line.customerHistoryLineCount) $customerHistory.Count
    Assert-DecimalNear $scenario "Recent customer median" ([decimal]$line.customerHistoryMedian) $customerMedian 0.0001
    Assert-DecimalNear $scenario "Proposed variance" ([decimal]$line.customerHistoryVariancePct) -10 0.01
    Assert-NotBlank $scenario "Latest customer history date" $line.customerHistoryLatestDate
    Assert-GreaterOrEqual $scenario "All-customer history count" ([decimal]$line.allCustomerHistoryLineCount) ([decimal]$customerHistory.Count)
    Assert-GreaterThanZero $scenario "All-customer median context" ([decimal]$line.allCustomerHistoryMedian)
    Assert-DecimalNear $scenario "Proposed price retained" ([decimal]$line.proposedSellPrice) $belowSell 0.0001
    Assert-NotBlank $scenario "History message" $line.historyMessage

    $audits = Get-QuoteAudits -QuoteEntryNo ([int]$s.Quote.entryNo)
    $historyAudit = @($audits | Where-Object { (ConvertFrom-BcEnum $_.eventType) -eq "Evaluated" -and [int]$_.lineNo -gt 0 }) | Select-Object -First 1
    Assert-Equal $scenario "Evaluation audit exists" ($null -ne $historyAudit) $true
    if ($historyAudit) {
        Assert-DecimalNear $scenario "Audit customer median snapshot" ([decimal]$historyAudit.customerHistoryMedian) $customerMedian 0.0001
        Assert-Equal $scenario "Audit history guardrail" (ConvertFrom-BcEnum $historyAudit.guardrailStatus) "Below Customer History"
    }

    $scenario = "Above Customer History"
    $s = New-HistoryQuote -Scenario $scenario -LandedCost $landedCost -ProposedSell $aboveSell
    Invoke-EvaluateQuote -QuoteId $s.Quote.id
    $line = Get-QuoteLine -LineId $s.LineId

    Assert-Equal $scenario "Guardrail status" (ConvertFrom-BcEnum $line.guardrailStatus) "Above Customer History"
    Assert-Equal $scenario "Needs approval" $line.needsApproval $true
    Assert-Equal $scenario "Exact history line count" ([int]$line.customerHistoryLineCount) $customerHistory.Count
    Assert-DecimalNear $scenario "Recent customer median" ([decimal]$line.customerHistoryMedian) $customerMedian 0.0001
    Assert-DecimalNear $scenario "Proposed variance" ([decimal]$line.customerHistoryVariancePct) 20 0.01
    Assert-DecimalNear $scenario "Proposed price retained" ([decimal]$line.proposedSellPrice) $aboveSell 0.0001
    Assert-NotBlank $scenario "History message" $line.historyMessage

    Assert-DecimalNear "All-Customer Context" "API and BC all-customer median agree" ([decimal]$line.allCustomerHistoryMedian) $allCustomerMedian 0.0001
}
finally {
    if ($QuoteBase) {
        foreach ($quoteId in $CreatedQuoteIds) {
            try {
                $null = Invoke-BcRequest -Method DELETE -Uri "$QuoteBase/packagingQuotes($quoteId)" -IfMatch -Body $null
            }
            catch {
                Write-Warning "Could not delete history UAT quote $quoteId. $($_.Exception.Message)"
            }
        }
    }

    $Secret = $null
    $Token = $null
}

Write-Host ""
Write-Host "HISTORY UAT RESULTS" -ForegroundColor Cyan
$Results | Format-Table Scenario, Check, Passed, Actual, Expected -AutoSize

$failed = @($Results | Where-Object { -not $_.Passed })
Write-Host ""
Write-Host "Checks run : $($Results.Count)"
Write-Host "Passed     : $($Results.Count - $failed.Count)"
Write-Host "Failed     : $($failed.Count)"
Write-Host "Cleanup    : temporary history UAT quotes and audit rows removed"

if ($failed.Count -gt 0) {
    Write-Host "PACKAGING CUSTOMER HISTORY API UAT FAILED" -ForegroundColor Red
    exit 1
}

Write-Host "PACKAGING CUSTOMER HISTORY API UAT PASSED" -ForegroundColor Green
exit 0
