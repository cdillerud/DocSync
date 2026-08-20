[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$CustomerNo = "TREEHUG",
    [string]$ProductNo = "F08234",
    [string]$BCItemNo = "F08234",
    [string]$QuoteUOM = "M",
    [string]$QuoteDate = "2026-08-19",
    [decimal]$TargetGrossMarginPct = 13,
    [decimal]$HistoryDiscountPct = 10,
    [string]$Description = "Tree Hugger F08234 Historical Landed-Cost Commercial Review"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Token = $null
$Secret = $null
$CompanyId = $null
$QuoteBase = $null
$CommercialBase = $null
$CompareBase = $null
$CreatedQuoteId = $null
$CreatedLineId = $null
$Succeeded = $false

function ConvertFrom-BcEnum {
    param([AllowNull()][string]$Value)

    if ($null -eq $Value) {
        return ""
    }

    return $Value.Replace("_x0020_", " ").Replace("_x002D_", "-").Trim()
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

function Get-AllBcRows {
    param([Parameter(Mandatory)][string]$Uri)

    $rows = [System.Collections.Generic.List[object]]::new()
    $nextUri = $Uri

    while (-not [string]::IsNullOrWhiteSpace($nextUri)) {
        $response = Invoke-BcRequest -Method GET -Uri $nextUri -Body $null
        foreach ($row in @($response.value)) {
            $rows.Add($row) | Out-Null
        }

        $nextProperty = $response.PSObject.Properties['@odata.nextLink']
        if ($nextProperty -and -not [string]::IsNullOrWhiteSpace([string]$nextProperty.Value)) {
            $nextUri = [string]$nextProperty.Value
        }
        else {
            $nextUri = $null
        }
    }

    return @($rows)
}

function Get-DecimalSum {
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][object[]]$Rows,
        [Parameter(Mandatory)][string]$PropertyName
    )

    [decimal]$total = 0
    foreach ($row in @($Rows)) {
        if ($null -eq $row) {
            continue
        }

        $property = $row.PSObject.Properties[$PropertyName]
        if ($null -eq $property -or $null -eq $property.Value) {
            continue
        }

        [decimal]$value = 0
        if ([decimal]::TryParse([string]$property.Value, [ref]$value)) {
            $total += $value
        }
    }

    return $total
}

function Get-RecentMedian {
    param([Parameter(Mandatory)][object[]]$Rows)

    $recent = @(
        $Rows |
            Sort-Object `
                @{ Expression = { [datetime]$_.postingDate }; Descending = $true }, `
                @{ Expression = { [string]$_.invoiceNo }; Descending = $true }, `
                @{ Expression = { [int]$_.lineNo }; Descending = $true } |
            Select-Object -First 5
    )

    $prices = @($recent | ForEach-Object { [decimal]$_.unitPrice } | Sort-Object)
    if ($prices.Count -eq 0) {
        return [decimal]0
    }

    if (($prices.Count % 2) -eq 1) {
        return [decimal]$prices[[int](($prices.Count - 1) / 2)]
    }

    $upper = [int]($prices.Count / 2)
    $lower = $upper - 1
    return [decimal](($prices[$lower] + $prices[$upper]) / 2)
}

function Convert-BcDateOrNull {
    param([AllowNull()][string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $null
    }

    $parsed = [datetime]$Value
    if ($parsed.Year -le 1) {
        return $null
    }

    return $parsed.Date
}

function Assert-Near {
    param(
        [Parameter(Mandatory)][decimal]$Actual,
        [Parameter(Mandatory)][decimal]$Expected,
        [decimal]$Tolerance = 0.0001,
        [Parameter(Mandatory)][string]$Label
    )

    if ([math]::Abs([double]($Actual - $Expected)) -gt [double]$Tolerance) {
        throw "$Label verification failed. Actual $Actual, expected $Expected +/- $Tolerance."
    }
}

try {
    Write-Host ""
    Write-Host "GPI CHARLIE FULL-FLOW DEMO QUOTE SETUP" -ForegroundColor Cyan
    Write-Host "Environment : $EnvironmentName"
    Write-Host "Customer    : $CustomerNo"
    Write-Host "Product     : $ProductNo"
    Write-Host "Quote date  : $QuoteDate"
    Write-Host ""

    if ($EnvironmentName -ne "Sandbox_NoZetadocs_UAT") {
        throw "This demo setup is restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
    }

    $quoteDateValue = [datetime]::ParseExact($QuoteDate, "yyyy-MM-dd", [System.Globalization.CultureInfo]::InvariantCulture).Date

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
    $CommercialBase = "$bcBase/api/gpi/commercialGuardrails/v1.0/companies($CompanyId)"
    $CompareBase = "$bcBase/api/gpi/packagingCompareUAT/v1.0/companies($CompanyId)"

    Write-Host "Company ID  : $CompanyId"
    Write-Host ""

    Write-Host "Preflight: verifying packaging product..." -ForegroundColor Yellow
    $productFilter = [uri]::EscapeDataString("productNo eq '$ProductNo'")
    $products = @(Get-AllBcRows -Uri "$CompareBase/packagingProductsUAT?`$filter=$productFilter")
    $product = @($products | Where-Object { [string]$_.bcItemNo -eq $BCItemNo }) | Select-Object -First 1
    if (-not $product) {
        throw "Packaging product $ProductNo mapped to BC Item $BCItemNo was not found."
    }

    Write-Host "Supplier cost : $($product.currentSupplierUnitCost) per EA"
    Write-Host "Vendor        : $($product.vendorNo)"
    Write-Host ""

    Write-Host "Preflight: reconstructing latest posted landed-cost evidence..." -ForegroundColor Yellow
    $valueFilter = [uri]::EscapeDataString("itemNo eq '$BCItemNo'")
    $valueRows = @(Get-AllBcRows -Uri "$CommercialBase/itemValueEvidence?`$filter=$valueFilter")
    $chargedLedgerNos = @(
        $valueRows |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) } |
            Select-Object -ExpandProperty itemLedgerEntryNo -Unique
    )

    if ($chargedLedgerNos.Count -eq 0) {
        throw "No posted item-charge landed-cost evidence exists for $BCItemNo."
    }

    $evidenceGroups = [System.Collections.Generic.List[object]]::new()
    foreach ($ledgerNo in $chargedLedgerNos) {
        $groupRows = @($valueRows | Where-Object { [int]$_.itemLedgerEntryNo -eq [int]$ledgerNo })
        $chargeRows = @($groupRows | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) })
        $directRows = @($groupRows | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) })

        $quantityCandidates = @(
            $groupRows |
                ForEach-Object { [math]::Abs([double][decimal]$_.valuedQuantity) } |
                Where-Object { $_ -gt 0 }
        )
        if ($quantityCandidates.Count -eq 0) {
            continue
        }

        $quantityEA = [decimal](($quantityCandidates | Measure-Object -Maximum).Maximum)
        $directActual = Get-DecimalSum -Rows $directRows -PropertyName 'costAmountActual'
        $totalCharges = Get-DecimalSum -Rows $chargeRows -PropertyName 'costAmountActual'
        $totalActual = $directActual + $totalCharges
        if ($quantityEA -le 0 -or $totalActual -le 0) {
            continue
        }

        $latestRow = @($groupRows | Sort-Object @{ Expression = { [datetime]$_.postingDate }; Descending = $true }, @{ Expression = { [int]$_.entryNo }; Descending = $true } | Select-Object -First 1)[0]
        $chargeCodes = @($chargeRows | ForEach-Object { [string]$_.itemChargeNo } | Sort-Object -Unique)

        $evidenceGroups.Add([pscustomobject]@{
            PostingDate = ([datetime]$latestRow.postingDate).Date
            ItemLedgerEntryNo = [int]$ledgerNo
            QuantityEA = $quantityEA
            DirectActual = $directActual
            TotalCharges = $totalCharges
            TotalActual = $totalActual
            LandedPerEA = [decimal]($totalActual / $quantityEA)
            ChargeCodes = ($chargeCodes -join ', ')
        }) | Out-Null
    }

    $latestEvidence = @(
        $evidenceGroups |
            Sort-Object `
                @{ Expression = { [datetime]$_.PostingDate }; Descending = $true }, `
                @{ Expression = { [int]$_.ItemLedgerEntryNo }; Descending = $true } |
            Select-Object -First 1
    )[0]
    if (-not $latestEvidence) {
        throw "Historical landed-cost evidence could not be reconstructed for $BCItemNo."
    }

    $landedPerEA = [decimal][math]::Round([double]$latestEvidence.LandedPerEA, 5, [System.MidpointRounding]::AwayFromZero)
    $landedPerM = [decimal][math]::Round([double]($landedPerEA * 1000), 5, [System.MidpointRounding]::AwayFromZero)

    Write-Host "Evidence date : $($latestEvidence.PostingDate.ToString('yyyy-MM-dd'))"
    Write-Host "ILE No.       : $($latestEvidence.ItemLedgerEntryNo)"
    Write-Host "Quantity      : $($latestEvidence.QuantityEA) EA"
    Write-Host "Direct actual : $($latestEvidence.DirectActual)"
    Write-Host "Item charges  : $($latestEvidence.TotalCharges)"
    Write-Host "Charge codes  : $($latestEvidence.ChargeCodes)"
    Write-Host "Landed / EA   : $landedPerEA"
    Write-Host "Landed / M    : $landedPerM"
    Write-Host ""

    Write-Host "Preflight: checking active protected-pricing rules..." -ForegroundColor Yellow
    $rules = Get-AllBcRows -Uri "$CommercialBase/pricingGuardrails"
    $applicableRules = @(
        $rules | Where-Object {
            $fromDate = Convert-BcDateOrNull -Value ([string]$_.effectiveFrom)
            $toDate = Convert-BcDateOrNull -Value ([string]$_.effectiveTo)
            $customerApplies = ([string]$_.customerNo -eq "") -or ([string]$_.customerNo -eq $CustomerNo)
            $itemApplies = ([string]$_.itemNo -eq "") -or ([string]$_.itemNo -eq $BCItemNo)
            $fromApplies = ($null -eq $fromDate) -or ($fromDate -le $quoteDateValue)
            $toApplies = ($null -eq $toDate) -or ($toDate -ge $quoteDateValue)
            $customerApplies -and $itemApplies -and $fromApplies -and $toApplies
        }
    )

    if ($applicableRules.Count -gt 0) {
        Write-Host "Applicable protected-pricing rules were found:" -ForegroundColor Red
        $applicableRules | Select-Object entryNo, customerNo, itemNo, ruleType, lockedSellPrice, effectiveFrom, effectiveTo, approver | Format-Table -AutoSize
        throw "Full-flow demo setup stopped because a Fixed Price or Special Pricing rule would take precedence over the customer-history scenario."
    }

    Write-Host "Preflight: reading exact posted customer history..." -ForegroundColor Yellow
    $historyFilterText = "customerNo eq '$CustomerNo' and itemNo eq '$BCItemNo' and unitOfMeasureCode eq '$QuoteUOM' and postingDate le $QuoteDate and quantity gt 0 and unitPrice gt 0"
    $historyFilter = [uri]::EscapeDataString($historyFilterText)
    $historyRows = @(Get-AllBcRows -Uri "$CommercialBase/historicalSalesLines?`$filter=$historyFilter")
    if ($historyRows.Count -lt 3) {
        throw "Only $($historyRows.Count) exact posted customer/item/UOM history line(s) were found. At least 3 are required."
    }

    $historyMedian = Get-RecentMedian -Rows $historyRows
    if ($historyMedian -le 0) {
        throw "The recent customer-history median is not positive."
    }

    $proposedSell = [decimal][math]::Round([double]($historyMedian * ((100 - $HistoryDiscountPct) / 100)), 2, [System.MidpointRounding]::AwayFromZero)
    $variancePct = [decimal][math]::Round([double]((($proposedSell - $historyMedian) / $historyMedian) * 100), 5, [System.MidpointRounding]::AwayFromZero)
    $grossMarginPct = [decimal][math]::Round([double]((($proposedSell - $landedPerM) / $proposedSell) * 100), 5, [System.MidpointRounding]::AwayFromZero)

    if ($grossMarginPct -lt $TargetGrossMarginPct) {
        throw "Proposed sell $proposedSell produces $grossMarginPct% GM, below target $TargetGrossMarginPct%. The margin rule would hide the intended customer-history exception."
    }

    Write-Host "History lines : $($historyRows.Count)"
    Write-Host "Recent-5 med. : $historyMedian"
    Write-Host "Proposed sell : $proposedSell ($variancePct% vs. median)"
    Write-Host "GM at sell    : $grossMarginPct%"
    Write-Host ""

    $notes = "UAT DEMO ONLY. Landed-cost basis uses historical posted Business Central Value Entry evidence dated $($latestEvidence.PostingDate.ToString('yyyy-MM-dd')), ILE $($latestEvidence.ItemLedgerEntryNo), with charges $($latestEvidence.ChargeCodes). This is not a current freight quote or current 2026 landed-cost rate."

    Write-Host "Creating clean Draft quote..." -ForegroundColor Yellow
    $quote = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuotes" -Body @{
        quoteDate = $QuoteDate
        customerNo = $CustomerNo
        description = $Description
        notes = $notes
    }
    $CreatedQuoteId = [string]$quote.id

    $line = Invoke-BcRequest -Method POST -Uri "$QuoteBase/packagingQuoteLines" -Body @{
        quoteEntryNo = [int]$quote.entryNo
        productNo = $ProductNo
    }
    $CreatedLineId = [string]$line.id

    $line = Invoke-BcRequest -Method PATCH -Uri "$QuoteBase/packagingQuoteLines($CreatedLineId)" -IfMatch -Body @{
        quantity = [decimal]$latestEvidence.QuantityEA
        landedCostPerUnit = $landedPerEA
        targetGrossMarginPct = $TargetGrossMarginPct
    }

    if ([string]$line.bcItemNo -ne $BCItemNo) {
        throw "Product $ProductNo mapped to BC Item '$($line.bcItemNo)' instead of expected '$BCItemNo'."
    }

    if ([string]$line.uomCode -ne "EA") {
        throw "Expected base UOM EA before UOM normalization, but Business Central returned '$($line.uomCode)'."
    }

    $line = Invoke-BcRequest -Method PATCH -Uri "$QuoteBase/packagingQuoteLines($CreatedLineId)" -IfMatch -Body @{
        uomCode = $QuoteUOM
    }

    $line = Invoke-BcRequest -Method PATCH -Uri "$QuoteBase/packagingQuoteLines($CreatedLineId)" -IfMatch -Body @{
        proposedSellPrice = $proposedSell
    }

    $quote = Invoke-BcRequest -Method GET -Uri "$QuoteBase/packagingQuotes($CreatedQuoteId)" -Body $null
    $line = Invoke-BcRequest -Method GET -Uri "$QuoteBase/packagingQuoteLines($CreatedLineId)" -Body $null

    if ((ConvertFrom-BcEnum ([string]$quote.status)) -ne "Draft") {
        throw "Demo quote status is '$($quote.status)' instead of Draft."
    }

    if ([string]$line.uomCode -ne $QuoteUOM) {
        throw "Demo line UOM is '$($line.uomCode)' instead of '$QuoteUOM'."
    }

    $expectedQtyM = [decimal]($latestEvidence.QuantityEA / 1000)
    Assert-Near -Actual ([decimal]$line.quantity) -Expected $expectedQtyM -Tolerance 0.00001 -Label "Demo quantity"
    Assert-Near -Actual ([decimal]$line.landedCostPerUnit) -Expected $landedPerM -Tolerance 0.00001 -Label "Demo landed cost"
    Assert-Near -Actual ([decimal]$line.proposedSellPrice) -Expected $proposedSell -Tolerance 0.00001 -Label "Demo proposed sell"

    if ((ConvertFrom-BcEnum ([string]$line.guardrailStatus)) -ne "Not Evaluated") {
        throw "Demo line guardrail status is '$($line.guardrailStatus)' instead of Not Evaluated."
    }

    if ([bool]$line.needsApproval) {
        throw "Demo line is already marked Needs Approval before evaluation."
    }

    if ([int]$quote.auditCount -ne 0) {
        throw "Demo quote already has $($quote.auditCount) audit entries. Expected a clean quote with 0."
    }

    $Succeeded = $true

    Write-Host ""
    Write-Host "CHARLIE FULL-FLOW DEMO QUOTE CREATED" -ForegroundColor Green
    Write-Host "Quote No.             : $($quote.entryNo)"
    Write-Host "Status                : $(ConvertFrom-BcEnum ([string]$quote.status))"
    Write-Host "Customer              : $($quote.customerNo) / $($quote.customerName)"
    Write-Host "Description           : $($quote.description)"
    Write-Host "Product               : $($line.productNo)"
    Write-Host "BC Item               : $($line.bcItemNo)"
    Write-Host "Quantity              : $($line.quantity)"
    Write-Host "UOM                   : $($line.uomCode)"
    Write-Host "Historical cost date  : $($latestEvidence.PostingDate.ToString('yyyy-MM-dd'))"
    Write-Host "Historical cost ILE   : $($latestEvidence.ItemLedgerEntryNo)"
    Write-Host "Charge codes          : $($latestEvidence.ChargeCodes)"
    Write-Host "Landed cost / unit    : $($line.landedCostPerUnit)"
    Write-Host "Proposed sell         : $($line.proposedSellPrice)"
    Write-Host "Target GM %           : $($line.targetGrossMarginPct)"
    Write-Host "Calculated GM %       : $($line.calculatedGrossMarginPct)"
    Write-Host "Guardrail status      : $(ConvertFrom-BcEnum ([string]$line.guardrailStatus))"
    Write-Host "Audit entries         : $($quote.auditCount)"
    Write-Host ""
    Write-Host "EXPECTED LIVE DEMO EVALUATION" -ForegroundColor Cyan
    Write-Host "History lines         : $($historyRows.Count)"
    Write-Host "Recent-5 median       : $historyMedian"
    Write-Host "Proposed variance     : $variancePct%"
    Write-Host "Expected guardrail    : Below Customer History"
    Write-Host "Expected approval     : Yes"
    Write-Host ""
    Write-Host "IMPORTANT" -ForegroundColor Yellow
    Write-Host "The quote notes explicitly identify the landed-cost basis as historical posted BC evidence, not a current 2026 freight quote."
    Write-Host "Leave this quote unevaluated until the live demo."
}
finally {
    $Secret = $null

    if (-not $Succeeded -and $Token -and $QuoteBase) {
        Write-Host ""
        Write-Host "Setup failed. Attempting to remove partial demo records..." -ForegroundColor Yellow

        if ($CreatedLineId) {
            try {
                Invoke-BcRequest -Method DELETE -Uri "$QuoteBase/packagingQuoteLines($CreatedLineId)" -IfMatch -Body $null | Out-Null
            }
            catch {
                Write-Warning "Could not delete partial quote line $CreatedLineId."
            }
        }

        if ($CreatedQuoteId) {
            try {
                Invoke-BcRequest -Method DELETE -Uri "$QuoteBase/packagingQuotes($CreatedQuoteId)" -IfMatch -Body $null | Out-Null
            }
            catch {
                Write-Warning "Could not delete partial quote $CreatedQuoteId."
            }
        }
    }
}
