[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$ReferenceProductNo = "TEST-12OZ-001"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Results = [System.Collections.Generic.List[object]]::new()
$CreatedProductIds = [System.Collections.Generic.List[string]]::new()
$CreatedVendorLocationIds = [System.Collections.Generic.List[string]]::new()
$CreatedRouteIds = [System.Collections.Generic.List[string]]::new()
$CreatedCompareIds = [System.Collections.Generic.List[string]]::new()

$Suffix = Get-Date -Format 'HHmmss'
$RunId = "ROUTE-API-UAT-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$DestinationState = "RTE$Suffix"
$OriginLatitude = [decimal]44.98000000
$OriginLongitude = [decimal]-93.27000000
$DestinationLatitude = [decimal]44.95000000
$DestinationLongitude = [decimal]-93.09000000
$RouteMiles = [decimal]12.50
$RouteMinutes = [decimal]22.0
$CostPerMile = [decimal]2.50

$Token = $null
$Secret = $null
$CompareBase = $null
$UatBase = $null

function ConvertFrom-BcEnum {
    param([AllowNull()][string]$Value)
    if ($null -eq $Value) { return "" }
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
    param([string]$Scenario, [string]$Check, [decimal]$Actual, [decimal]$Expected, [decimal]$Tolerance = 0.0001)
    $passed = ([math]::Abs([double]($Actual - $Expected)) -le [double]$Tolerance)
    Add-TestResult -Scenario $Scenario -Check $Check -Passed $passed -Actual $Actual -Expected "$Expected +/- $Tolerance"
}

function Assert-GreaterThan {
    param([string]$Scenario, [string]$Check, [decimal]$Actual, [decimal]$ExpectedLower)
    Add-TestResult -Scenario $Scenario -Check $Check -Passed ($Actual -gt $ExpectedLower) -Actual $Actual -Expected "> $ExpectedLower"
}

function Assert-Contains {
    param([string]$Scenario, [string]$Check, [AllowNull()][string]$Actual, [string]$ExpectedFragment)
    $passed = ([string]$Actual).IndexOf($ExpectedFragment, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
    Add-TestResult -Scenario $Scenario -Check $Check -Passed $passed -Actual $Actual -Expected "contains '$ExpectedFragment'"
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
    if ($IfMatch) { $headers["If-Match"] = "*" }

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

function Get-ReferenceProduct {
    $filterText = [uri]::EscapeDataString("productNo eq '$ReferenceProductNo'")
    $response = Invoke-BcRequest -Method GET -Uri "$UatBase/packagingProductsUAT?`$filter=$filterText" -Body $null
    return @($response.value) | Select-Object -First 1
}

function New-UatVendorLocation {
    param([Parameter(Mandatory)]$ReferenceProduct, [Parameter(Mandatory)][string]$LocationCode)

    $location = Invoke-BcRequest -Method POST -Uri "$UatBase/vendorLocationsUAT" -Body @{
        vendorNo = $ReferenceProduct.vendorNo
        locationCode = $LocationCode
        description = "$RunId route origin"
        city = "UAT Route Origin"
        stateProvince = "MN"
        latitude = $OriginLatitude
        longitude = $OriginLongitude
        defaultFob = $false
        blocked = $false
    }
    $CreatedVendorLocationIds.Add([string]$location.id) | Out-Null
    return $location
}

function New-UatProduct {
    param([Parameter(Mandatory)]$ReferenceProduct, [Parameter(Mandatory)][string]$ProductNo, [Parameter(Mandatory)][string]$LocationCode)

    $product = Invoke-BcRequest -Method POST -Uri "$UatBase/packagingProductsUAT" -Body @{
        productNo = $ProductNo
        material = $ReferenceProduct.material
        style = $ReferenceProduct.style
        capacity = [decimal]$ReferenceProduct.capacity
        capacityUom = $ReferenceProduct.capacityUom
        color = $ReferenceProduct.color
        bcItemNo = $ReferenceProduct.bcItemNo
        vendorNo = $ReferenceProduct.vendorNo
        vendorLocationCode = $LocationCode
        transportMode = $ReferenceProduct.transportMode
        fullLoadQuantity = [decimal]$ReferenceProduct.fullLoadQuantity
        noOfPallets = [decimal]$ReferenceProduct.noOfPallets
        gramWeight = [decimal]$ReferenceProduct.gramWeight
        currentSupplierUnitCost = [decimal]$ReferenceProduct.currentSupplierUnitCost
        blocked = $false
    }
    $CreatedProductIds.Add([string]$product.id) | Out-Null
    return $product
}

function New-UatRouteCache {
    param([Parameter(Mandatory)]$ReferenceProduct)

    $now = (Get-Date).ToUniversalTime()
    $route = Invoke-BcRequest -Method POST -Uri "$UatBase/routeCacheUAT" -Body @{
        originLatitude = $OriginLatitude
        originLongitude = $OriginLongitude
        destinationLatitude = $DestinationLatitude
        destinationLongitude = $DestinationLongitude
        mode = $ReferenceProduct.transportMode
        distanceMiles = $RouteMiles
        durationMinutes = $RouteMinutes
        provider = "Manual"
        calculatedAt = $now.ToString("yyyy-MM-ddTHH:mm:ssZ")
        expiresAt = $now.AddDays(7).ToString("yyyy-MM-ddTHH:mm:ssZ")
        providerReference = $RunId
        notes = "Deterministic route mileage UAT cache seed"
    }
    $CreatedRouteIds.Add([string]$route.id) | Out-Null
    return $route
}

function New-Comparison {
    $compare = Invoke-BcRequest -Method POST -Uri "$CompareBase/packagingComparisons" -Body @{
        comparisonDate = (Get-Date).ToString("yyyy-MM-dd")
        description = $RunId
        referenceProductNo = $ReferenceProductNo
        destinationState = $DestinationState
        destinationLatitude = $DestinationLatitude
        destinationLongitude = $DestinationLongitude
        targetGrossMarginPct = 25
        palletCostPerPallet = 0
        tariffPct = 0
        internationalFreightTotal = 0
        customsTotal = 0
        deliveryTotal = 0
        defaultCostPerMile = $CostPerMile
        allowMileageFallback = $true
        autoRouteMileage = $true
    }
    $CreatedCompareIds.Add([string]$compare.id) | Out-Null
    return $compare
}

function Invoke-AddMatching {
    param([string]$CompareId)
    $null = Invoke-BcRequest -Method POST -Uri "$CompareBase/packagingComparisons($CompareId)/Microsoft.NAV.addMatchingCandidates" -Body @{}
}

function Invoke-Calculate {
    param([string]$CompareId)
    $null = Invoke-BcRequest -Method POST -Uri "$CompareBase/packagingComparisons($CompareId)/Microsoft.NAV.calculate" -Body @{}
}

function Get-Comparison {
    param([string]$CompareId)
    return Invoke-BcRequest -Method GET -Uri "$CompareBase/packagingComparisons($CompareId)" -Body $null
}

function Get-Lines {
    param([int]$EntryNo)
    $filterText = [uri]::EscapeDataString("compareEntryNo eq $EntryNo")
    $response = Invoke-BcRequest -Method GET -Uri "$CompareBase/packagingComparisonLines?`$filter=$filterText" -Body $null
    return @($response.value)
}

try {
    Write-Host ""
    Write-Host "GPI PACKAGING ROUTE MILEAGE API UAT" -ForegroundColor Cyan
    Write-Host "Run ID      : $RunId"
    Write-Host "Environment : $EnvironmentName"
    Write-Host "Reference   : $ReferenceProductNo"
    Write-Host "Destination : $DestinationState"
    Write-Host "Route miles : $RouteMiles"
    Write-Host "Cost / mile : $CostPerMile"
    Write-Host ""

    if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw "Azure CLI (az) is required." }

    $accountJson = & az account show --output json --only-show-errors 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($accountJson | Out-String))) {
        & az login --tenant $TenantId --only-show-errors | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Azure login failed." }
    }

    $Secret = (& az keyvault secret show --vault-name $KeyVaultName --name "bc-client-secret" --query value --output tsv --only-show-errors).Trim()
    if ([string]::IsNullOrWhiteSpace($Secret)) { throw "Could not retrieve bc-client-secret from Key Vault $KeyVaultName." }

    $tokenResponse = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType "application/x-www-form-urlencoded" -Body @{
        grant_type = "client_credentials"
        client_id = $ClientId
        client_secret = $Secret
        scope = "https://api.businesscentral.dynamics.com/.default"
    }
    $Token = [string]$tokenResponse.access_token
    if ([string]::IsNullOrWhiteSpace($Token)) { throw "Microsoft identity platform did not return an access token." }

    $bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
    $companies = Invoke-BcRequest -Method GET -Uri "$bcBase/api/v2.0/companies" -Body $null
    $company = @($companies.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
    if (-not $company) { throw "Company '$CompanyName' was not returned by the Business Central API." }

    $companyId = [string]$company.id
    $CompareBase = "$bcBase/api/gpi/packagingComparisons/v1.0/companies($companyId)"
    $UatBase = "$bcBase/api/gpi/packagingCompareUAT/v1.0/companies($companyId)"
    Write-Host "Company ID  : $companyId"
    Write-Host ""

    $reference = Get-ReferenceProduct
    if (-not $reference) { throw "Reference product '$ReferenceProductNo' was not returned by the sandbox UAT API." }
    if ([string]::IsNullOrWhiteSpace([string]$reference.vendorNo)) { throw "Reference product must have a Vendor No." }
    if ([decimal]$reference.fullLoadQuantity -le 0) { throw "Reference product must have a positive Full Load Quantity." }

    $locationCode = "RT$Suffix"
    $productNo = "RTP$Suffix"

    $null = New-UatVendorLocation -ReferenceProduct $reference -LocationCode $locationCode
    $null = New-UatProduct -ReferenceProduct $reference -ProductNo $productNo -LocationCode $locationCode
    $route = New-UatRouteCache -ReferenceProduct $reference

    $compare = New-Comparison
    Invoke-AddMatching -CompareId $compare.id
    Invoke-Calculate -CompareId $compare.id

    $compare = Get-Comparison -CompareId $compare.id
    $lines = Get-Lines -EntryNo ([int]$compare.entryNo)
    $line = @($lines | Where-Object { $_.productNo -eq $productNo }) | Select-Object -First 1

    if (-not $line) { throw "Temporary route product '$productNo' was not added to the comparison." }

    $scenario = "Cached Route Resolution"
    Assert-DecimalNear $scenario "Origin latitude snapshot" ([decimal]$line.originLatitude) $OriginLatitude 0.000001
    Assert-DecimalNear $scenario "Origin longitude snapshot" ([decimal]$line.originLongitude) $OriginLongitude 0.000001
    Assert-DecimalNear $scenario "Cached route miles used" ([decimal]$line.routeMiles) $RouteMiles 0.0001
    Assert-DecimalNear $scenario "Cached route duration used" ([decimal]$line.routeDurationMinutes) $RouteMinutes 0.01
    Assert-Equal $scenario "Route provider" (ConvertFrom-BcEnum $line.routeProvider) "Manual"
    Assert-Contains $scenario "Route message identifies cache" $line.routeMessage "cache entry"
    Assert-GreaterThan $scenario "Route cache entry created" ([decimal]$route.entryNo) 0

    $scenario = "Mileage Freight Fallback"
    $expectedFreight = [decimal]($RouteMiles * $CostPerMile)
    $expectedFreightPerUnit = [decimal]($expectedFreight / [decimal]$reference.fullLoadQuantity)
    Assert-Equal $scenario "Candidate rankable" $line.isComplete $true
    Assert-Equal $scenario "Freight basis" (ConvertFrom-BcEnum $line.freightBasis) "Mileage"
    Assert-DecimalNear $scenario "Mileage cost per mile" ([decimal]$line.mileageCostPerMile) $CostPerMile 0.0001
    Assert-DecimalNear $scenario "Domestic freight total" ([decimal]$line.domesticFreightTotal) $expectedFreight 0.01
    Assert-DecimalNear $scenario "Domestic freight per unit" ([decimal]$line.domesticFreightPerUnit) $expectedFreightPerUnit 0.0001
    Assert-GreaterThan $scenario "Landed cost includes freight" ([decimal]$line.landedCostPerUnit) ([decimal]$line.supplierUnitCost)
    Assert-GreaterThan $scenario "Suggested sell exceeds landed cost" ([decimal]$line.suggestedSellPrice) ([decimal]$line.landedCostPerUnit)

    $scenario = "Stale Route Safety"
    $newDestinationLatitude = $DestinationLatitude + [decimal]0.01000000
    $null = Invoke-BcRequest -Method PATCH -Uri "$CompareBase/packagingComparisons($($compare.id))" -IfMatch -Body @{
        destinationLatitude = $newDestinationLatitude
    }
    $linesAfterPatch = Get-Lines -EntryNo ([int]$compare.entryNo)
    $lineAfterPatch = @($linesAfterPatch | Where-Object { $_.productNo -eq $productNo }) | Select-Object -First 1
    Assert-DecimalNear $scenario "Destination change clears route miles" ([decimal]$lineAfterPatch.routeMiles) 0 0.0001
    Assert-Equal $scenario "Destination change invalidates rankability" $lineAfterPatch.isComplete $false
    Assert-Equal $scenario "Destination change clears freight basis" (ConvertFrom-BcEnum $lineAfterPatch.freightBasis) "None"
}
finally {
    if ($CompareBase) {
        foreach ($compareId in $CreatedCompareIds) {
            try { $null = Invoke-BcRequest -Method DELETE -Uri "$CompareBase/packagingComparisons($compareId)" -IfMatch -Body $null }
            catch { Write-Warning "Could not delete UAT comparison $compareId. $($_.Exception.Message)" }
        }
    }

    if ($UatBase) {
        foreach ($routeId in $CreatedRouteIds) {
            try { $null = Invoke-BcRequest -Method DELETE -Uri "$UatBase/routeCacheUAT($routeId)" -IfMatch -Body $null }
            catch { Write-Warning "Could not delete UAT route cache $routeId. $($_.Exception.Message)" }
        }
        foreach ($productId in $CreatedProductIds) {
            try { $null = Invoke-BcRequest -Method DELETE -Uri "$UatBase/packagingProductsUAT($productId)" -IfMatch -Body $null }
            catch { Write-Warning "Could not delete UAT product $productId. $($_.Exception.Message)" }
        }
        foreach ($locationId in $CreatedVendorLocationIds) {
            try { $null = Invoke-BcRequest -Method DELETE -Uri "$UatBase/vendorLocationsUAT($locationId)" -IfMatch -Body $null }
            catch { Write-Warning "Could not delete UAT vendor location $locationId. $($_.Exception.Message)" }
        }
    }

    $Secret = $null
    $Token = $null
}

Write-Host ""
Write-Host "ROUTE MILEAGE UAT RESULTS" -ForegroundColor Cyan
$Results | Format-Table Scenario, Check, Passed, Actual, Expected -AutoSize

$failed = @($Results | Where-Object { -not $_.Passed })
Write-Host ""
Write-Host "Checks run : $($Results.Count)"
Write-Host "Passed     : $($Results.Count - $failed.Count)"
Write-Host "Failed     : $($failed.Count)"
Write-Host "Cleanup    : temporary comparison, route cache, product, and vendor location removed"

if ($failed.Count -gt 0) {
    Write-Host "PACKAGING ROUTE MILEAGE API UAT FAILED" -ForegroundColor Red
    exit 1
}

Write-Host "PACKAGING ROUTE MILEAGE API UAT PASSED" -ForegroundColor Green
exit 0
