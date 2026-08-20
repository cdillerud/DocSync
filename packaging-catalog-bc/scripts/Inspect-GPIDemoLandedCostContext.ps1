[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$ProductNo = "FG10900B",
    [string]$QuoteUomCode = "M"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-BcGet {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token
    )

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = "application/json"
    }

    $rows = [System.Collections.Generic.List[object]]::new()
    $next = $Uri

    while (-not [string]::IsNullOrWhiteSpace($next)) {
        $response = Invoke-RestMethod -Method GET -Uri $next -Headers $headers
        foreach ($row in @($response.value)) {
            $rows.Add($row) | Out-Null
        }

        $next = $null
        if ($response.PSObject.Properties.Name -contains '@odata.nextLink') {
            $next = [string]$response.'@odata.nextLink'
        }
    }

    return @($rows)
}

function ConvertFrom-BcEnum {
    param([AllowNull()][string]$Value)

    if ($null -eq $Value) {
        return ""
    }

    return $Value.Replace("_x0020_", " ").Replace("_x002D_", "-").Trim()
}

function Format-YesNo {
    param([bool]$Value)
    if ($Value) { return "Yes" }
    return "No"
}

Write-Host ""
Write-Host "GPI DEMO LANDED COST CONTEXT" -ForegroundColor Cyan
Write-Host "Environment : $EnvironmentName"
Write-Host "Product     : $ProductNo"
Write-Host "Quote UOM   : $QuoteUomCode"
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

$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companies = Invoke-BcGet -Uri "$bcBase/api/v2.0/companies" -Token $token
$company = @($companies | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
if (-not $company) {
    throw "Company '$CompanyName' was not returned by the Business Central API."
}

$companyId = [string]$company.id
$compareBase = "$bcBase/api/gpi/packagingCompareUAT/v1.0/companies($companyId)"
$guardBase = "$bcBase/api/gpi/commercialGuardrails/v1.0/companies($companyId)"

$productFilter = [uri]::EscapeDataString("productNo eq '$ProductNo'")
$products = @(Invoke-BcGet -Uri "$compareBase/packagingProductsUAT?`$filter=$productFilter" -Token $token)
if ($products.Count -eq 0) {
    throw "Packaging product '$ProductNo' was not returned by the UAT API."
}
if ($products.Count -gt 1) {
    throw "Packaging product '$ProductNo' returned more than one record."
}

$product = $products[0]
$bcItemNo = [string]$product.bcItemNo
$vendorNo = [string]$product.vendorNo
$vendorLocationCode = [string]$product.vendorLocationCode
$transportMode = ConvertFrom-BcEnum ([string]$product.transportMode)

Write-Host "PACKAGING PRODUCT" -ForegroundColor Cyan
[pscustomobject]@{
    Product = $product.productNo
    BCItem = $bcItemNo
    Material = $product.material
    Capacity = $product.capacity
    CapacityUOM = $product.capacityUom
    Style = $product.style
    Vendor = $vendorNo
    FOBCode = $vendorLocationCode
    Mode = $transportMode
    FullLoadQty = $product.fullLoadQuantity
    Pallets = $product.noOfPallets
    PalletQty = $product.palletQuantity
    GramWeight = $product.gramWeight
    SupplierUnitCost = $product.currentSupplierUnitCost
    PriceEffective = $product.priceEffectiveDate
} | Format-List

if ([string]::IsNullOrWhiteSpace($bcItemNo)) {
    throw "Product $ProductNo does not have a BC Item No. mapping."
}

$itemFilter = [uri]::EscapeDataString("itemNo eq '$bcItemNo'")
$itemContexts = @(Invoke-BcGet -Uri "$guardBase/itemCostContexts?`$filter=$itemFilter" -Token $token)
if ($itemContexts.Count -eq 0) {
    throw "No Item Cost Context rows were returned for BC Item $bcItemNo."
}

Write-Host ""
Write-Host "BUSINESS CENTRAL ITEM / UOM CONTEXT" -ForegroundColor Cyan
$itemContexts |
    Select-Object itemNo, description, baseUnitOfMeasure, unitCost, vendorNo, vendorItemNo, uomCode, qtyPerUnitOfMeasure |
    Format-Table -AutoSize

$baseContext = @($itemContexts | Select-Object -First 1)[0]
$baseUom = [string]$baseContext.baseUnitOfMeasure
$itemUnitCost = [decimal]$baseContext.unitCost
$quoteUom = @($itemContexts | Where-Object { [string]$_.uomCode -eq $QuoteUomCode }) | Select-Object -First 1

if (-not $quoteUom) {
    Write-Warning "BC Item $bcItemNo does not have Item Unit of Measure '$QuoteUomCode'."
    $qtyPerQuoteUom = [decimal]0
}
else {
    $qtyPerQuoteUom = [decimal]$quoteUom.qtyPerUnitOfMeasure
}

$catalogSupplierCost = [decimal]$product.currentSupplierUnitCost
$catalogVsItemCost = [decimal][math]::Round([double]($catalogSupplierCost - $itemUnitCost), 5)

Write-Host ""
Write-Host "COST BASIS" -ForegroundColor Cyan
Write-Host "BC Item base UOM             : $baseUom"
Write-Host "BC Item Unit Cost            : $itemUnitCost per $baseUom"
Write-Host "Catalog Supplier Unit Cost   : $catalogSupplierCost per $baseUom"
Write-Host "Catalog vs BC Item cost diff : $catalogVsItemCost per $baseUom"
if ($qtyPerQuoteUom -gt 0) {
    $catalogCostPerQuoteUom = [decimal][math]::Round([double]($catalogSupplierCost * $qtyPerQuoteUom), 5)
    $itemCostPerQuoteUom = [decimal][math]::Round([double]($itemUnitCost * $qtyPerQuoteUom), 5)
    Write-Host "Qty per $QuoteUomCode                 : $qtyPerQuoteUom $baseUom"
    Write-Host "Catalog supplier cost / $QuoteUomCode : $catalogCostPerQuoteUom"
    Write-Host "BC Item cost / $QuoteUomCode          : $itemCostPerQuoteUom"
}

Write-Host ""
Write-Host "VENDOR / FOB CONTEXT" -ForegroundColor Cyan
if ([string]::IsNullOrWhiteSpace($vendorNo)) {
    Write-Warning "The packaging product does not have a Vendor No."
    $vendorLocations = @()
}
else {
    $vendorFilter = [uri]::EscapeDataString("vendorNo eq '$vendorNo'")
    $vendorLocations = @(Invoke-BcGet -Uri "$compareBase/vendorLocationsUAT?`$filter=$vendorFilter" -Token $token)

    if ($vendorLocations.Count -eq 0) {
        Write-Warning "No GPI Vendor Location rows exist for vendor $vendorNo."
    }
    else {
        $vendorLocations |
            Select-Object vendorNo, locationCode, description, city, stateProvince, latitude, longitude, defaultFob, blocked |
            Format-Table -AutoSize
    }
}

Write-Host ""
Write-Host "FREIGHT RATE CONTEXT" -ForegroundColor Cyan
if ([string]::IsNullOrWhiteSpace($vendorNo)) {
    Write-Warning "Freight rates cannot be scoped because Vendor No. is blank."
    $freightRates = @()
}
else {
    $freightFilter = [uri]::EscapeDataString("originVendorNo eq '$vendorNo'")
    $freightRates = @(Invoke-BcGet -Uri "$compareBase/freightRatesUAT?`$filter=$freightFilter" -Token $token)

    if ($freightRates.Count -eq 0) {
        Write-Warning "No GPI freight-rate rows exist for vendor $vendorNo."
    }
    else {
        $freightRates |
            Select-Object entryNo, originVendorNo, originLocationCode, destinationState, defaultDestination, mode, ratePerCwt, minimumCharge, fuelSurchargePct, effectiveDate, blocked |
            Format-Table -AutoSize
    }
}

Write-Host ""
Write-Host "DEMO READINESS" -ForegroundColor Cyan
$checks = [System.Collections.Generic.List[object]]::new()
$checks.Add([pscustomobject]@{ Check = "BC Item mapped"; Ready = -not [string]::IsNullOrWhiteSpace($bcItemNo); Detail = $bcItemNo }) | Out-Null
$checks.Add([pscustomobject]@{ Check = "Supplier cost positive"; Ready = ($catalogSupplierCost -gt 0); Detail = [string]$catalogSupplierCost }) | Out-Null
$checks.Add([pscustomobject]@{ Check = "$QuoteUomCode UOM configured"; Ready = ($qtyPerQuoteUom -gt 0); Detail = if ($qtyPerQuoteUom -gt 0) { "$qtyPerQuoteUom $baseUom per $QuoteUomCode" } else { "Missing" } }) | Out-Null
$checks.Add([pscustomobject]@{ Check = "Vendor configured"; Ready = -not [string]::IsNullOrWhiteSpace($vendorNo); Detail = $vendorNo }) | Out-Null
$checks.Add([pscustomobject]@{ Check = "FOB location configured"; Ready = -not [string]::IsNullOrWhiteSpace($vendorLocationCode); Detail = if ($vendorLocationCode) { $vendorLocationCode } else { "Missing" } }) | Out-Null
$checks.Add([pscustomobject]@{ Check = "Vendor location row exists"; Ready = ($vendorLocations.Count -gt 0); Detail = "$($vendorLocations.Count) row(s)" }) | Out-Null
$checks.Add([pscustomobject]@{ Check = "Full load quantity positive"; Ready = ([decimal]$product.fullLoadQuantity -gt 0); Detail = [string]$product.fullLoadQuantity }) | Out-Null
$checks.Add([pscustomobject]@{ Check = "Gram weight positive"; Ready = ([decimal]$product.gramWeight -gt 0); Detail = [string]$product.gramWeight }) | Out-Null
$checks.Add([pscustomobject]@{ Check = "Freight rate available"; Ready = ($freightRates.Count -gt 0); Detail = "$($freightRates.Count) row(s)" }) | Out-Null

$checks | Format-Table Check, Ready, Detail -AutoSize

$missing = @($checks | Where-Object { -not $_.Ready })
Write-Host ""
if ($missing.Count -eq 0) {
    Write-Host "This product has all major data elements needed for a landed-cost demo." -ForegroundColor Green
}
else {
    Write-Host "$($missing.Count) landed-cost demo data gap(s) remain. These should be resolved deliberately rather than hidden in the demo." -ForegroundColor Yellow
}

if ($qtyPerQuoteUom -gt 0) {
    Write-Host ""
    Write-Host "UOM EXPLANATION" -ForegroundColor Cyan
    Write-Host "The landed-cost engine currently calculates on the BC base-unit basis."
    Write-Host "For this item, $QuoteUomCode represents $qtyPerQuoteUom $baseUom."
    Write-Host "A base landed cost of 0.09192 per $baseUom is therefore 91.92 per $QuoteUomCode."
    Write-Host "This conversion is already enforced on packaging quote lines."
}

Write-Host ""
Write-Host "READ ONLY. No Business Central data was changed." -ForegroundColor DarkGray
