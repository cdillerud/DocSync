[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$ProductNo = "F08234",
    [string]$BCItemNo = "F08234",
    [string]$QuoteDate = "2026-08-19",
    [decimal]$HistoryDiscountPct = 10,
    [decimal]$TargetGrossMarginPct = 13
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-BcGetAll {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token
    )

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = "application/json"
    }

    $rows = [System.Collections.Generic.List[object]]::new()
    $nextUri = $Uri

    while (-not [string]::IsNullOrWhiteSpace($nextUri)) {
        $response = Invoke-RestMethod -Method GET -Uri $nextUri -Headers $headers
        foreach ($row in @($response.value)) {
            $rows.Add($row) | Out-Null
        }

        $nextUri = $null
        $nextProperty = $response.PSObject.Properties['@odata.nextLink']
        if ($nextProperty -and -not [string]::IsNullOrWhiteSpace([string]$nextProperty.Value)) {
            $nextUri = [string]$nextProperty.Value
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
        if ($null -eq $row) { continue }
        $property = $row.PSObject.Properties[$PropertyName]
        if ($null -eq $property -or $null -eq $property.Value) { continue }
        [decimal]$value = 0
        if ([decimal]::TryParse([string]$property.Value, [ref]$value)) {
            $total += $value
        }
    }
    return $total
}

function Get-Median {
    param([decimal[]]$Values)

    if ($null -eq $Values -or $Values.Count -eq 0) {
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

function Get-GrossMarginPct {
    param(
        [decimal]$Cost,
        [decimal]$Sell
    )

    if ($Sell -le 0) {
        return [decimal]0
    }

    return [decimal][math]::Round([double]((($Sell - $Cost) / $Sell) * 100), 5)
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

Write-Host ""
Write-Host "GPI END-TO-END DEMO CANDIDATE" -ForegroundColor Cyan
Write-Host "Environment : $EnvironmentName"
Write-Host "Product     : $ProductNo"
Write-Host "BC Item     : $BCItemNo"
Write-Host "Quote date  : $QuoteDate"
Write-Host ""

if ($EnvironmentName -ne "Sandbox_NoZetadocs_UAT") {
    throw "This inspection script is restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
}

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

$secret = (& az keyvault secret show --vault-name $KeyVaultName --name "bc-client-secret" --query value --output tsv --only-show-errors).Trim()
if ([string]::IsNullOrWhiteSpace($secret)) {
    throw "Could not retrieve bc-client-secret from Key Vault $KeyVaultName."
}

try {
    $tokenResponse = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType "application/x-www-form-urlencoded" -Body @{
        grant_type = "client_credentials"
        client_id = $ClientId
        client_secret = $secret
        scope = "https://api.businesscentral.dynamics.com/.default"
    }
}
finally {
    $secret = $null
}

$token = [string]$tokenResponse.access_token
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "Microsoft identity platform did not return an access token."
}

$quoteDateValue = [datetime]::ParseExact($QuoteDate, "yyyy-MM-dd", [System.Globalization.CultureInfo]::InvariantCulture).Date
$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companies = Invoke-BcGetAll -Uri "$bcBase/api/v2.0/companies" -Token $token
$company = @($companies | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
if (-not $company) {
    throw "Company '$CompanyName' was not returned by the Business Central API."
}

$companyId = [string]$company.id
$commercialBase = "$bcBase/api/gpi/commercialGuardrails/v1.0/companies($companyId)"
$compareBase = "$bcBase/api/gpi/packagingCompareUAT/v1.0/companies($companyId)"

Write-Host "Company ID  : $companyId"
Write-Host ""

$productFilter = [uri]::EscapeDataString("productNo eq '$ProductNo'")
$products = @(Invoke-BcGetAll -Uri "$compareBase/packagingProductsUAT?`$filter=$productFilter" -Token $token)
$product = $products | Select-Object -First 1
if (-not $product) {
    throw "Packaging product $ProductNo was not returned by the UAT product API."
}
if ([string]$product.bcItemNo -ne $BCItemNo) {
    throw "Packaging product $ProductNo maps to BC Item '$($product.bcItemNo)' instead of expected '$BCItemNo'."
}

Write-Host "PRODUCT CONTEXT" -ForegroundColor Cyan
[pscustomobject]@{
    Product = $product.productNo
    BCItem = $product.bcItemNo
    Material = $product.material
    Capacity = $product.capacity
    CapacityUOM = $product.capacityUom
    Vendor = $product.vendorNo
    SupplierUnitCost = $product.currentSupplierUnitCost
    GramWeight = $product.gramWeight
} | Format-List

$itemFilter = [uri]::EscapeDataString("itemNo eq '$BCItemNo'")
$itemContexts = @(Invoke-BcGetAll -Uri "$commercialBase/itemCostContexts?`$filter=$itemFilter" -Token $token)
if ($itemContexts.Count -eq 0) {
    throw "No Item Cost Context rows were returned for $BCItemNo."
}

$valueRows = @(Invoke-BcGetAll -Uri "$commercialBase/itemValueEvidence?`$filter=$itemFilter" -Token $token)
$chargedGroups = @(
    $valueRows |
        Group-Object itemLedgerEntryNo |
        ForEach-Object {
            $rows = @($_.Group)
            $chargeRows = @($rows | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) })
            if ($chargeRows.Count -eq 0) { return }

            $qtyCandidates = @(
                $rows |
                    ForEach-Object { [math]::Abs([double][decimal]$_.invoicedQuantity) } |
                    Where-Object { $_ -gt 0 }
            )
            if ($qtyCandidates.Count -eq 0) {
                $qtyCandidates = @(
                    $rows |
                        ForEach-Object { [math]::Abs([double][decimal]$_.valuedQuantity) } |
                        Where-Object { $_ -gt 0 }
                )
            }
            $quantity = if ($qtyCandidates.Count -gt 0) { [decimal](($qtyCandidates | Measure-Object -Maximum).Maximum) } else { [decimal]0 }

            $directRows = @($rows | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) })
            $direct = Get-DecimalSum -Rows $directRows -PropertyName 'costAmountActual'
            $freight = Get-DecimalSum -Rows @($chargeRows | Where-Object { ([string]$_.itemChargeNo).ToUpperInvariant() -eq 'FREIGHT' }) -PropertyName 'costAmountActual'
            $customs = Get-DecimalSum -Rows @($chargeRows | Where-Object { ([string]$_.itemChargeNo).ToUpperInvariant() -eq 'CUSTOMS' }) -PropertyName 'costAmountActual'
            $drayage = Get-DecimalSum -Rows @($chargeRows | Where-Object { ([string]$_.itemChargeNo).ToUpperInvariant() -eq 'DRAYAGE' }) -PropertyName 'costAmountActual'
            $tariff = Get-DecimalSum -Rows @($chargeRows | Where-Object { ([string]$_.itemChargeNo).ToUpperInvariant() -eq 'TARIFF' }) -PropertyName 'costAmountActual'
            $energy = Get-DecimalSum -Rows @($chargeRows | Where-Object { ([string]$_.itemChargeNo).ToUpperInvariant() -eq 'ENERGY' }) -PropertyName 'costAmountActual'
            $known = $freight + $customs + $drayage + $tariff + $energy
            $totalCharges = Get-DecimalSum -Rows $chargeRows -PropertyName 'costAmountActual'
            $other = $totalCharges - $known
            $total = $direct + $totalCharges
            $latestRow = @($rows | Sort-Object @{ Expression = { [datetime]$_.postingDate }; Descending = $true }, @{ Expression = { [int]$_.entryNo }; Descending = $true } | Select-Object -First 1)[0]
            $codes = @($chargeRows | ForEach-Object { [string]$_.itemChargeNo } | Sort-Object -Unique)

            [pscustomobject]@{
                PostingDate = [datetime]$latestRow.postingDate
                ItemLedgerEntryNo = [int]$_.Name
                QuantityEA = $quantity
                DirectActual = $direct
                Freight = $freight
                Customs = $customs
                Drayage = $drayage
                Tariff = $tariff
                Energy = $energy
                OtherCharges = $other
                TotalCharges = $totalCharges
                TotalActual = $total
                DirectPerEA = if ($quantity -gt 0) { [decimal][math]::Round([double]($direct / $quantity), 5) } else { [decimal]0 }
                ChargesPerEA = if ($quantity -gt 0) { [decimal][math]::Round([double]($totalCharges / $quantity), 5) } else { [decimal]0 }
                LandedPerEA = if ($quantity -gt 0) { [decimal][math]::Round([double]($total / $quantity), 5) } else { [decimal]0 }
                ChargeCodes = ($codes -join ', ')
            }
        } |
        Sort-Object @{ Expression = { $_.PostingDate }; Descending = $true }
)

if ($chargedGroups.Count -eq 0) {
    throw "No posted item-charge landed-cost evidence was found for $BCItemNo."
}

$latestCharged = $chargedGroups[0]

Write-Host "LATEST POSTED LANDED-COST EVIDENCE" -ForegroundColor Cyan
$latestCharged | Format-List PostingDate, ItemLedgerEntryNo, QuantityEA, DirectActual, Freight, Customs, Drayage, Tariff, Energy, OtherCharges, TotalCharges, TotalActual, DirectPerEA, ChargesPerEA, LandedPerEA, ChargeCodes

$historyRaw = @(Invoke-BcGetAll -Uri "$commercialBase/historicalSalesLines?`$filter=$itemFilter" -Token $token)
$history = @(
    $historyRaw | Where-Object {
        ([decimal]$_.quantity -gt 0) -and
        ([decimal]$_.unitPrice -gt 0) -and
        ([datetime]$_.postingDate -le $quoteDateValue)
    }
)

$historyCandidates = @(
    $history |
        Group-Object customerNo, unitOfMeasureCode |
        ForEach-Object {
            $groupRows = @($_.Group)
            if ($groupRows.Count -lt 3) { return }

            $recentFive = @(
                $groupRows |
                    Sort-Object `
                        @{ Expression = { [datetime]$_.postingDate }; Descending = $true }, `
                        @{ Expression = { [string]$_.invoiceNo }; Descending = $true }, `
                        @{ Expression = { [int]$_.lineNo }; Descending = $true } |
                    Select-Object -First 5
            )
            $median = Get-Median -Values @($recentFive | ForEach-Object { [decimal]$_.unitPrice })
            $latest = @($groupRows | Sort-Object @{ Expression = { [datetime]$_.postingDate }; Descending = $true } | Select-Object -First 1)[0]
            $uom = [string]$latest.unitOfMeasureCode
            $uomContext = @($itemContexts | Where-Object { [string]$_.uomCode -eq $uom }) | Select-Object -First 1
            if (-not $uomContext) { return }
            $qtyPerUom = [decimal]$uomContext.qtyPerUnitOfMeasure
            if ($qtyPerUom -le 0) { return }

            $landedPerUom = [decimal][math]::Round([double]($latestCharged.LandedPerEA * $qtyPerUom), 5)
            $proposedSell = [decimal][math]::Round([double]($median * ((100 - $HistoryDiscountPct) / 100)), 2, [System.MidpointRounding]::AwayFromZero)
            $variancePct = [decimal][math]::Round([double]((($proposedSell - $median) / $median) * 100), 5)
            $gm = Get-GrossMarginPct -Cost $landedPerUom -Sell $proposedSell

            [pscustomobject]@{
                CustomerNo = [string]$latest.customerNo
                CustomerName = [string]$latest.customerName
                UOM = $uom
                QtyPerUOM = $qtyPerUom
                HistoryLines = $groupRows.Count
                Recent5Median = $median
                ProposedSell = $proposedSell
                VariancePct = $variancePct
                LatestHistoryDate = [datetime]$latest.postingDate
                LandedCostPerUOM = $landedPerUom
                GrossMarginPct = $gm
                ClearsTargetGM = ($gm -ge $TargetGrossMarginPct)
            }
        } |
        Sort-Object `
            @{ Expression = { if ($_.ClearsTargetGM) { 0 } else { 1 } } }, `
            @{ Expression = { $_.HistoryLines }; Descending = $true }, `
            @{ Expression = { $_.LatestHistoryDate }; Descending = $true }
)

Write-Host ""
Write-Host "CUSTOMER HISTORY OPTIONS USING LATEST POSTED LANDED EVIDENCE" -ForegroundColor Cyan
if ($historyCandidates.Count -eq 0) {
    Write-Host "No customer/item/UOM combination has at least 3 exact posted positive sales lines through $QuoteDate." -ForegroundColor Yellow
    Write-Host "READ ONLY. No Business Central data was changed." -ForegroundColor DarkGray
    exit 0
}

$historyCandidates |
    Select-Object -First 15 CustomerNo, CustomerName, UOM, QtyPerUOM, HistoryLines, Recent5Median, ProposedSell, VariancePct, LandedCostPerUOM, GrossMarginPct, ClearsTargetGM, LatestHistoryDate |
    Format-Table -AutoSize -Wrap

$recommended = $historyCandidates[0]

$rules = @(Invoke-BcGetAll -Uri "$commercialBase/pricingGuardrails" -Token $token)
$applicableRules = @(
    $rules | Where-Object {
        $fromDate = Convert-BcDateOrNull -Value ([string]$_.effectiveFrom)
        $toDate = Convert-BcDateOrNull -Value ([string]$_.effectiveTo)
        $customerApplies = ([string]$_.customerNo -eq '') -or ([string]$_.customerNo -eq $recommended.CustomerNo)
        $itemApplies = ([string]$_.itemNo -eq '') -or ([string]$_.itemNo -eq $BCItemNo)
        $fromApplies = ($null -eq $fromDate) -or ($fromDate -le $quoteDateValue)
        $toApplies = ($null -eq $toDate) -or ($toDate -ge $quoteDateValue)
        $customerApplies -and $itemApplies -and $fromApplies -and $toApplies
    }
)

Write-Host ""
Write-Host "RECOMMENDED END-TO-END DEMO CONTEXT" -ForegroundColor Green
Write-Host "Product                : $ProductNo"
Write-Host "BC Item                : $BCItemNo"
Write-Host "Latest charged date    : $($latestCharged.PostingDate.ToString('yyyy-MM-dd'))"
Write-Host "Posted charge codes    : $($latestCharged.ChargeCodes)"
Write-Host "Historical landed / EA : $($latestCharged.LandedPerEA)"
Write-Host "Customer               : $($recommended.CustomerNo) / $($recommended.CustomerName)"
Write-Host "Quote / history UOM    : $($recommended.UOM)"
Write-Host "Qty per UOM            : $($recommended.QtyPerUOM) EA"
Write-Host "Historical landed / UOM: $($recommended.LandedCostPerUOM)"
Write-Host "Exact history lines    : $($recommended.HistoryLines)"
Write-Host "Recent-5 median sell   : $($recommended.Recent5Median)"
Write-Host "Demo proposed sell     : $($recommended.ProposedSell)"
Write-Host "Proposed variance      : $($recommended.VariancePct)%"
Write-Host "GM at proposed sell    : $($recommended.GrossMarginPct)%"
Write-Host "Target GM              : $TargetGrossMarginPct%"
Write-Host "Clears target GM       : $($recommended.ClearsTargetGM)"
Write-Host "Protected rules found  : $($applicableRules.Count)"

if ($applicableRules.Count -gt 0) {
    Write-Host ""
    Write-Host "APPLICABLE PROTECTED-PRICING RULES" -ForegroundColor Red
    $applicableRules | Select-Object entryNo, customerNo, itemNo, ruleType, lockedSellPrice, effectiveFrom, effectiveTo, approver | Format-Table -AutoSize
    Write-Host "This candidate is not clean for a customer-history-first demo because protected pricing would take precedence." -ForegroundColor Red
}
elseif (-not $recommended.ClearsTargetGM) {
    Write-Host ""
    Write-Host "This candidate has strong data, but the 10% below-history sell falls below the configured target GM. Margin would take precedence over history in the guardrail result." -ForegroundColor Yellow
}
else {
    Write-Host ""
    Write-Host "DEMO READY" -ForegroundColor Green
    Write-Host "This candidate has recent posted landed-cost evidence, exact customer history, no applicable protected-pricing rule, and enough margin for the history exception to remain the visible guardrail reason." -ForegroundColor Green
}

Write-Host ""
Write-Host "IMPORTANT" -ForegroundColor Yellow
Write-Host "The landed-cost evidence is historical posted Business Central cost, not a current freight quote. Use it to explain and validate the cost model."
Write-Host "Do not present the historical landed value as a current 2026 rate without a current authoritative freight source."
Write-Host ""
Write-Host "READ ONLY. No Business Central data was changed." -ForegroundColor DarkGray
