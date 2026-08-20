[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [datetime]$MinimumPostingDate = [datetime]"2025-01-01",
    [int]$Top = 25
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-BcGetAll {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token
    )

    $headers = @{ Authorization = "Bearer $Token"; Accept = "application/json" }
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

Write-Host ""
Write-Host "GPI RECENT LANDED-COST DEMO CANDIDATES" -ForegroundColor Cyan
Write-Host "Environment          : $EnvironmentName"
Write-Host "Minimum posting date : $($MinimumPostingDate.ToString('yyyy-MM-dd'))"
Write-Host ""

if ($EnvironmentName -ne "Sandbox_NoZetadocs_UAT") {
    throw "This discovery script is restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI (az) is required."
}

$accountJson = & az account show --output json --only-show-errors 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($accountJson | Out-String))) {
    & az login --tenant $TenantId --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Azure login failed." }
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
if ([string]::IsNullOrWhiteSpace($token)) { throw "Microsoft identity platform did not return an access token." }

$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companies = Invoke-BcGetAll -Uri "$bcBase/api/v2.0/companies" -Token $token
$company = @($companies | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
if (-not $company) { throw "Company '$CompanyName' was not returned by the Business Central API." }

$companyId = [string]$company.id
$compareBase = "$bcBase/api/gpi/packagingCompareUAT/v1.0/companies($companyId)"
$guardBase = "$bcBase/api/gpi/commercialGuardrails/v1.0/companies($companyId)"

$products = @(Invoke-BcGetAll -Uri "$compareBase/packagingProductsUAT" -Token $token)
$mappedProducts = @($products | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.bcItemNo) })

Write-Host "Mapped packaging products : $($mappedProducts.Count)"
Write-Host ""

$candidates = [System.Collections.Generic.List[object]]::new()

foreach ($product in $mappedProducts) {
    $itemNo = [string]$product.bcItemNo
    $itemFilter = [uri]::EscapeDataString("itemNo eq '$itemNo'")

    try {
        $valueRows = @(Invoke-BcGetAll -Uri "$guardBase/itemValueEvidence?`$filter=$itemFilter" -Token $token)
    }
    catch {
        Write-Warning "Could not read Value Entry evidence for $itemNo. $($_.Exception.Message)"
        continue
    }

    $chargeRows = @($valueRows | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) })
    if ($chargeRows.Count -eq 0) { continue }

    $chargedLedgerNos = @($chargeRows | ForEach-Object { [int]$_.itemLedgerEntryNo } | Sort-Object -Unique)

    foreach ($ledgerNo in $chargedLedgerNos) {
        $groupRows = @($valueRows | Where-Object { [int]$_.itemLedgerEntryNo -eq $ledgerNo })
        $thisChargeRows = @($groupRows | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) })
        if ($thisChargeRows.Count -eq 0) { continue }

        $latestRow = @($groupRows | Sort-Object @{Expression={ [datetime]$_.postingDate };Descending=$true}, @{Expression={ [int]$_.entryNo };Descending=$true} | Select-Object -First 1)[0]
        $postingDate = [datetime]$latestRow.postingDate
        if ($postingDate -lt $MinimumPostingDate) { continue }

        $qtyCandidates = @(
            $groupRows |
                ForEach-Object { [math]::Abs([double][decimal]$_.invoicedQuantity) } |
                Where-Object { $_ -gt 0 }
        )
        if ($qtyCandidates.Count -eq 0) {
            $qtyCandidates = @(
                $groupRows |
                    ForEach-Object { [math]::Abs([double][decimal]$_.valuedQuantity) } |
                    Where-Object { $_ -gt 0 }
            )
        }
        $quantityEA = if ($qtyCandidates.Count -gt 0) { [decimal](($qtyCandidates | Measure-Object -Maximum).Maximum) } else { [decimal]0 }
        if ($quantityEA -le 0) { continue }

        $directRows = @($groupRows | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.itemChargeNo) })
        $directActual = Get-DecimalSum -Rows $directRows -PropertyName 'costAmountActual'
        $freight = Get-DecimalSum -Rows @($thisChargeRows | Where-Object { ([string]$_.itemChargeNo).ToUpperInvariant() -eq 'FREIGHT' }) -PropertyName 'costAmountActual'
        $customs = Get-DecimalSum -Rows @($thisChargeRows | Where-Object { ([string]$_.itemChargeNo).ToUpperInvariant() -eq 'CUSTOMS' }) -PropertyName 'costAmountActual'
        $drayage = Get-DecimalSum -Rows @($thisChargeRows | Where-Object { ([string]$_.itemChargeNo).ToUpperInvariant() -eq 'DRAYAGE' }) -PropertyName 'costAmountActual'
        $allCharges = Get-DecimalSum -Rows $thisChargeRows -PropertyName 'costAmountActual'
        $other = $allCharges - $freight - $customs - $drayage
        $totalActual = $directActual + $allCharges
        $landedEA = [decimal][math]::Round([double]($totalActual / $quantityEA), 5)
        $directEA = [decimal][math]::Round([double]($directActual / $quantityEA), 5)
        $chargesEA = [decimal][math]::Round([double]($allCharges / $quantityEA), 5)

        $mQty = [decimal]0
        try {
            $uomRows = @(Invoke-BcGetAll -Uri "$guardBase/itemCostContexts?`$filter=$itemFilter" -Token $token)
            $mRow = @($uomRows | Where-Object { [string]$_.uomCode -eq 'M' }) | Select-Object -First 1
            if ($mRow) { $mQty = [decimal]$mRow.qtyPerUnitOfMeasure }
        }
        catch {
            $mQty = 0
        }

        $candidates.Add([pscustomobject]@{
            ProductNo = [string]$product.productNo
            BCItemNo = $itemNo
            Material = [string]$product.material
            Capacity = [decimal]$product.capacity
            CapacityUOM = [string]$product.capacityUom
            VendorNo = [string]$product.vendorNo
            PostingDate = $postingDate
            ItemLedgerEntryNo = $ledgerNo
            QuantityEA = $quantityEA
            DirectPerEA = $directEA
            ChargesPerEA = $chargesEA
            LandedPerEA = $landedEA
            LandedPerM = if ($mQty -gt 0) { [decimal][math]::Round([double]($landedEA * $mQty), 2) } else { $null }
            Freight = $freight
            Customs = $customs
            Drayage = $drayage
            OtherCharges = $other
            ChargeCodes = (@($thisChargeRows | ForEach-Object { [string]$_.itemChargeNo } | Sort-Object -Unique) -join ', ')
        }) | Out-Null
    }
}

$latestPerItem = @(
    $candidates |
        Group-Object BCItemNo |
        ForEach-Object {
            $_.Group |
                Sort-Object @{Expression={ [datetime]$_.PostingDate };Descending=$true}, @{Expression={ [int]$_.ItemLedgerEntryNo };Descending=$true} |
                Select-Object -First 1
        } |
        Sort-Object @{Expression={ [datetime]$_.PostingDate };Descending=$true}, BCItemNo |
        Select-Object -First $Top
)

Write-Host "RECENT CHARGED COST CANDIDATES" -ForegroundColor Cyan
if ($latestPerItem.Count -eq 0) {
    Write-Host "No controlled packaging-catalog item has posted item-charge evidence on or after $($MinimumPostingDate.ToString('yyyy-MM-dd'))." -ForegroundColor Yellow
}
else {
    $latestPerItem |
        Format-Table ProductNo, BCItemNo, Material, Capacity, CapacityUOM, VendorNo, PostingDate, QuantityEA, DirectPerEA, ChargesPerEA, LandedPerEA, LandedPerM, ChargeCodes -AutoSize
}

Write-Host ""
Write-Host "Candidate items found : $($latestPerItem.Count)"
Write-Host "READ ONLY. No Business Central data was changed." -ForegroundColor DarkGray
