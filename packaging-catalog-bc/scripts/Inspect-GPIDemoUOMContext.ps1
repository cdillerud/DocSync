[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$BCItemNo = "FG10900B",
    [string]$CustomerNo = "WAT",
    [string]$QuoteUomCode = "M",
    [decimal]$BaseLandedCostPerUnit = 0.09192
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

    return [decimal][math]::Round([double]((($Sell - $Cost) / $Sell) * 100), 2)
}

Write-Host ""
Write-Host "GPI DEMO UOM AND PRICING CONTEXT" -ForegroundColor Cyan
Write-Host "Environment          : $EnvironmentName"
Write-Host "BC Item              : $BCItemNo"
Write-Host "Customer             : $CustomerNo"
Write-Host "History / quote UOM  : $QuoteUomCode"
Write-Host "Base landed cost/unit: $BaseLandedCostPerUnit"
Write-Host ""

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
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
$guardBase = "$bcBase/api/gpi/commercialGuardrails/v1.0/companies($companyId)"

$itemFilter = [uri]::EscapeDataString("itemNo eq '$BCItemNo'")
$itemContexts = @(Invoke-BcGet -Uri "$guardBase/itemCostContexts?`$filter=$itemFilter" -Token $token)
if ($itemContexts.Count -eq 0) {
    throw "No Item Cost Context rows were returned for $BCItemNo."
}

$baseUom = [string](@($itemContexts | Select-Object -First 1)[0].baseUnitOfMeasure)
$quoteUom = @($itemContexts | Where-Object { [string]$_.uomCode -eq $QuoteUomCode }) | Select-Object -First 1
if (-not $quoteUom) {
    Write-Host "ITEM UOM ROWS" -ForegroundColor Yellow
    $itemContexts | Select-Object itemNo, baseUnitOfMeasure, unitCost, uomCode, qtyPerUnitOfMeasure | Format-Table -AutoSize
    throw "Item $BCItemNo does not have Item Unit of Measure '$QuoteUomCode'."
}

$qtyPerUom = [decimal]$quoteUom.qtyPerUnitOfMeasure
if ($qtyPerUom -le 0) {
    throw "Qty. per Unit of Measure for $BCItemNo / $QuoteUomCode is not positive."
}

$convertedLandedCost = [decimal][math]::Round([double]($BaseLandedCostPerUnit * $qtyPerUom), 5)

$historyFilter = [uri]::EscapeDataString("customerNo eq '$CustomerNo' and itemNo eq '$BCItemNo' and unitOfMeasureCode eq '$QuoteUomCode'")
$historyRaw = @(Invoke-BcGet -Uri "$guardBase/historicalSalesLines?`$filter=$historyFilter" -Token $token)
$asOfDate = (Get-Date).Date.AddDays(1).AddTicks(-1)
$history = @(
    $historyRaw |
        Where-Object {
            ([decimal]$_.quantity -gt 0) -and
            ([decimal]$_.unitPrice -gt 0) -and
            ([datetime]$_.postingDate -le $asOfDate)
        }
)

$recentFive = @(
    $history |
        Sort-Object `
            @{ Expression = { [datetime]$_.postingDate }; Descending = $true }, `
            @{ Expression = { [string]$_.invoiceNo }; Descending = $true }, `
            @{ Expression = { [int]$_.lineNo }; Descending = $true } |
        Select-Object -First 5
)
$median = Get-Median -Values @($recentFive | ForEach-Object { [decimal]$_.unitPrice })
$below = if ($median -gt 0) { [decimal][math]::Round([double]($median * [decimal]0.90), 5) } else { [decimal]0 }
$above = if ($median -gt 0) { [decimal][math]::Round([double]($median * [decimal]1.20), 5) } else { [decimal]0 }

Write-Host "ITEM UOM CONTEXT" -ForegroundColor Cyan
$itemContexts |
    Select-Object itemNo, baseUnitOfMeasure, unitCost, uomCode, qtyPerUnitOfMeasure |
    Format-Table -AutoSize

Write-Host ""
Write-Host "QUOTE 55 CONVERSION CHECK" -ForegroundColor Cyan
Write-Host "Base UOM                 : $baseUom"
Write-Host "Quote/history UOM        : $QuoteUomCode"
Write-Host "Qty per quote UOM        : $qtyPerUom"
Write-Host "Base landed cost/unit    : $BaseLandedCostPerUnit per $baseUom"
Write-Host "Converted landed cost    : $convertedLandedCost per $QuoteUomCode"
Write-Host ""

Write-Host "CUSTOMER HISTORY CONTEXT" -ForegroundColor Cyan
Write-Host "Exact posted lines       : $($history.Count)"
Write-Host "Recent-5 median sell     : $median per $QuoteUomCode"
Write-Host "Below-history test sell  : $below per $QuoteUomCode"
Write-Host "Above-history test sell  : $above per $QuoteUomCode"
if ($median -gt 0) {
    Write-Host "GP at median             : $(Get-GrossMarginPct -Cost $convertedLandedCost -Sell $median)%"
    Write-Host "GP at below-history sell : $(Get-GrossMarginPct -Cost $convertedLandedCost -Sell $below)%"
    Write-Host "GP at above-history sell : $(Get-GrossMarginPct -Cost $convertedLandedCost -Sell $above)%"
}

Write-Host ""
if (($baseUom -ne $QuoteUomCode) -and ($qtyPerUom -ne 1)) {
    Write-Host "IMPORTANT" -ForegroundColor Yellow
    Write-Host "Quote pricing and landed cost must use the same UOM basis."
    Write-Host "Do not compare a $BaseLandedCostPerUnit-per-$baseUom landed cost directly to a $QuoteUomCode sales price."
    Write-Host "For this item, the equivalent landed cost is $convertedLandedCost per $QuoteUomCode."
}
else {
    Write-Host "The base and quote UOM basis do not require a quantity conversion for this item." -ForegroundColor Green
}

Write-Host ""
Write-Host "READ ONLY. No Business Central data was changed." -ForegroundColor DarkGray
