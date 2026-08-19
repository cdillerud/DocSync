[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$OutputRoot = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Token = $null
$Secret = $null

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
        [Parameter(Mandatory)][ValidateSet("GET", "POST")][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [AllowNull()]$Body
    )

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = "application/json"
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

function Get-BcPagedCollection {
    param([Parameter(Mandatory)][string]$Uri)

    $rows = [System.Collections.Generic.List[object]]::new()
    $next = $Uri

    while (-not [string]::IsNullOrWhiteSpace($next)) {
        $response = Invoke-BcRequest -Method GET -Uri $next -Body $null
        foreach ($row in @($response.value)) {
            $rows.Add($row) | Out-Null
        }

        $nextProperty = $response.PSObject.Properties['@odata.nextLink']
        if ($null -ne $nextProperty -and -not [string]::IsNullOrWhiteSpace([string]$nextProperty.Value)) {
            $next = [string]$nextProperty.Value
        }
        else {
            $next = $null
        }
    }

    return @($rows)
}

function ConvertFrom-BcEnum {
    param([AllowNull()][string]$Value)
    if ($null -eq $Value) { return "" }
    return $Value.Replace("_x0020_", " ").Replace("_x002D_", "-").Trim()
}

try {
    Write-Host ""
    Write-Host "GPI BUSINESS CENTRAL ITEM DISCOVERY" -ForegroundColor Cyan
    Write-Host "Environment : $EnvironmentName"
    Write-Host "Company     : $CompanyName"
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
    $discoveryBase = "$bcBase/api/gpi/catalogDiscovery/v1.0/companies($companyId)"
    $uatBase = "$bcBase/api/gpi/packagingCompareUAT/v1.0/companies($companyId)"

    Write-Host "Company ID  : $companyId"
    Write-Host ""

    $items = @(Get-BcPagedCollection -Uri "$discoveryBase/bcItems")
    if ($items.Count -eq 0) {
        throw "The BC Item discovery API returned no items."
    }

    $firstItemId = [string]$items[0].id
    $null = Invoke-BcRequest -Method POST -Uri "$discoveryBase/bcItems($firstItemId)/Microsoft.NAV.refreshFieldMetadata" -Body @{}
    $itemFields = @(Get-BcPagedCollection -Uri "$discoveryBase/bcItemFields")

    $packagingProducts = @()
    try {
        $packagingProducts = @(Get-BcPagedCollection -Uri "$uatBase/packagingProductsUAT")
    }
    catch {
        Write-Warning "Could not read sandbox packagingProductsUAT. Mapping coverage will be omitted. $($_.Exception.Message)"
    }

    if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
        $OutputRoot = Join-Path $PSScriptRoot "..\artifacts\bc-item-discovery"
    }

    $runFolder = Join-Path ([System.IO.Path]::GetFullPath($OutputRoot)) (Get-Date -Format "yyyyMMdd-HHmmss")
    New-Item -ItemType Directory -Path $runFolder -Force | Out-Null

    $mapping = @{}
    foreach ($product in $packagingProducts) {
        $bcItemNo = [string]$product.bcItemNo
        if ([string]::IsNullOrWhiteSpace($bcItemNo)) { continue }

        if (-not $mapping.ContainsKey($bcItemNo)) {
            $mapping[$bcItemNo] = [System.Collections.Generic.List[string]]::new()
        }
        $mapping[$bcItemNo].Add([string]$product.productNo) | Out-Null
    }

    $itemExport = foreach ($item in $items) {
        $itemNo = [string]$item.itemNo
        $mappedProducts = ""
        if ($mapping.ContainsKey($itemNo)) {
            $mappedProducts = ($mapping[$itemNo] -join ";")
        }

        [pscustomobject]@{
            ItemNo = $itemNo
            Description = [string]$item.description
            Description2 = [string]$item.description2
            ItemType = ConvertFrom-BcEnum ([string]$item.itemType)
            BaseUnitOfMeasure = [string]$item.baseUnitOfMeasure
            ItemCategoryCode = [string]$item.itemCategoryCode
            VendorNo = [string]$item.vendorNo
            VendorItemNo = [string]$item.vendorItemNo
            UnitCost = [decimal]$item.unitCost
            LastDirectCost = [decimal]$item.lastDirectCost
            GrossWeight = [decimal]$item.grossWeight
            NetWeight = [decimal]$item.netWeight
            UnitsPerParcel = [decimal]$item.unitsPerParcel
            UnitVolume = [decimal]$item.unitVolume
            ManufacturerCode = [string]$item.manufacturerCode
            CountryRegionOriginCode = [string]$item.countryRegionOriginCode
            Blocked = [bool]$item.blocked
            PurchasingBlocked = [bool]$item.purchasingBlocked
            SalesBlocked = [bool]$item.salesBlocked
            SystemModifiedAt = [string]$item.systemModifiedAt
            PackagingCatalogMapped = (-not [string]::IsNullOrWhiteSpace($mappedProducts))
            GpiPackagingProductNos = $mappedProducts
        }
    }

    $itemCsv = Join-Path $runFolder "BC_Items.csv"
    $fieldCsv = Join-Path $runFolder "BC_Item_Fields.csv"
    $customFieldCsv = Join-Path $runFolder "BC_Item_Fields_Likely_Custom.csv"
    $categoryCsv = Join-Path $runFolder "BC_Item_Category_Summary.csv"
    $packagingCsv = Join-Path $runFolder "Existing_GPI_Packaging_Products.csv"
    $summaryPath = Join-Path $runFolder "BC_Item_Discovery_Summary.txt"

    $itemExport | Sort-Object ItemNo | Export-Csv -LiteralPath $itemCsv -NoTypeInformation -Encoding UTF8
    $itemFields | Sort-Object { [int]$_.fieldNo } | Export-Csv -LiteralPath $fieldCsv -NoTypeInformation -Encoding UTF8

    $likelyCustomFields = @(
        $itemFields |
            Where-Object {
                ([int]$_.fieldNo -ge 50000) -and
                ([int]$_.fieldNo -lt 2000000000)
            } |
            Sort-Object { [int]$_.fieldNo }
    )
    $likelyCustomFields | Export-Csv -LiteralPath $customFieldCsv -NoTypeInformation -Encoding UTF8

    $categorySummary = @(
        $itemExport |
            Group-Object ItemCategoryCode |
            ForEach-Object {
                $categoryName = $_.Name
                if ([string]::IsNullOrWhiteSpace($categoryName)) { $categoryName = "<blank>" }
                [pscustomobject]@{
                    ItemCategoryCode = $categoryName
                    ItemCount = $_.Count
                    ActiveCount = @($_.Group | Where-Object { -not $_.Blocked }).Count
                    WithVendorCount = @($_.Group | Where-Object { -not [string]::IsNullOrWhiteSpace($_.VendorNo) }).Count
                    WithLastDirectCostCount = @($_.Group | Where-Object { $_.LastDirectCost -gt 0 }).Count
                    WithNetWeightCount = @($_.Group | Where-Object { $_.NetWeight -gt 0 }).Count
                    PackagingCatalogMappedCount = @($_.Group | Where-Object { $_.PackagingCatalogMapped }).Count
                }
            } |
            Sort-Object ItemCount -Descending
    )
    $categorySummary | Export-Csv -LiteralPath $categoryCsv -NoTypeInformation -Encoding UTF8

    if ($packagingProducts.Count -gt 0) {
        $packagingProducts | Export-Csv -LiteralPath $packagingCsv -NoTypeInformation -Encoding UTF8
    }
    else {
        "No packagingProductsUAT rows were returned." | Set-Content -LiteralPath $packagingCsv -Encoding UTF8
    }

    $totalItems = $itemExport.Count
    $activeItems = @($itemExport | Where-Object { -not $_.Blocked }).Count
    $withVendor = @($itemExport | Where-Object { -not [string]::IsNullOrWhiteSpace($_.VendorNo) }).Count
    $withLastDirectCost = @($itemExport | Where-Object { $_.LastDirectCost -gt 0 }).Count
    $withNetWeight = @($itemExport | Where-Object { $_.NetWeight -gt 0 }).Count
    $mappedItems = @($itemExport | Where-Object { $_.PackagingCatalogMapped }).Count

    $summary = @(
        "GPI BUSINESS CENTRAL ITEM DISCOVERY",
        "Run Time                 : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "Environment              : $EnvironmentName",
        "Company                  : $CompanyName",
        "Company ID               : $companyId",
        "",
        "Total BC Items           : $totalItems",
        "Active BC Items          : $activeItems",
        "Items with Vendor No.    : $withVendor",
        "Items with Last Direct Cost: $withLastDirectCost",
        "Items with Net Weight    : $withNetWeight",
        "Already mapped to GPI catalog: $mappedItems",
        "Item table fields found  : $($itemFields.Count)",
        "Likely custom fields     : $($likelyCustomFields.Count)",
        "",
        "NOTE: 'Likely custom fields' uses field number >= 50000 and < 2000000000 as a discovery heuristic only.",
        "No BC Item data was modified by this script."
    )
    $summary | Set-Content -LiteralPath $summaryPath -Encoding UTF8

    Write-Host "BC ITEM DISCOVERY COMPLETE" -ForegroundColor Green
    Write-Host "Total items              : $totalItems"
    Write-Host "Active items             : $activeItems"
    Write-Host "With Vendor No.          : $withVendor"
    Write-Host "With Last Direct Cost    : $withLastDirectCost"
    Write-Host "With Net Weight          : $withNetWeight"
    Write-Host "Already catalog-mapped   : $mappedItems"
    Write-Host "Item fields discovered   : $($itemFields.Count)"
    Write-Host "Likely custom fields     : $($likelyCustomFields.Count)"
    Write-Host ""
    Write-Host "Output folder: $runFolder" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "No Business Central Item records were changed."
}
finally {
    $Token = $null
    $Secret = $null
    Remove-Variable tokenResponse -ErrorAction SilentlyContinue
}
