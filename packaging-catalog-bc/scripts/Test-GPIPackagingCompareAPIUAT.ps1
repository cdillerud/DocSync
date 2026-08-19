[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$ReferenceProductNo = "TEST-12OZ-001",
    [string]$DestinationState = "UAT8"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Results = [System.Collections.Generic.List[object]]::new()
$CreatedProductIds = [System.Collections.Generic.List[string]]::new()
$CreatedRateIds = [System.Collections.Generic.List[string]]::new()
$CreatedCompareIds = [System.Collections.Generic.List[string]]::new()
$CreatedVendorLocationIds = [System.Collections.Generic.List[string]]::new()
$RunId = "COMPARE-API-UAT-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
$Suffix = Get-Date -Format 'HHmmss'
$DestinationState = "$DestinationState$Suffix"
$Token = $null
$Secret = $null
$CompareBase = $null
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

function Assert-LessThan {
    param([string]$Scenario, [string]$Check, [decimal]$Actual, [decimal]$ExpectedUpper)
    Add-TestResult -Scenario $Scenario -Check $Check -Passed ($Actual -lt $ExpectedUpper) -Actual $Actual -Expected "< $ExpectedUpper"
}

function Assert-GreaterThan {
    param([string]$Scenario, [string]$Check, [decimal]$Actual, [decimal]$ExpectedLower)
    Add-TestResult -Scenario $Scenario -Check $Check -Passed ($Actual -gt $ExpectedLower) -Actual $Actual -Expected "> $ExpectedLower"
}

function Assert-GreaterOrEqual {
    param([string]$Scenario, [string]$Check, [decimal]$Actual, [decimal]$ExpectedMinimum)
    Add-TestResult -Scenario $Scenario -Check $Check -Passed ($Actual -ge $ExpectedMinimum) -Actual $Actual -Expected ">= $ExpectedMinimum"
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

function Get-ReferenceProduct {
    $filterText = [uri]::EscapeDataString("productNo eq '$ReferenceProductNo'")
    $response = Invoke-BcRequest -Method GET -Uri "$UatBase/packagingProductsUAT?`$filter=$filterText" -Body $null
    return @($response.value) | Select-Object -First 1
}

function New-UatVendorLocation {
    param(
        [Parameter(Mandatory)]$ReferenceProduct,
        [Parameter(Mandatory)][string]$LocationCode
    )

    $location = Invoke-BcRequest -Method POST -Uri "$UatBase/vendorLocationsUAT" -Body @{
        vendorNo = $ReferenceProduct.vendorNo
        code = $LocationCode
        description = "$RunId no freight"
        city = "UAT"
        stateProvince = "UAT"
        defaultFob = $false
        blocked = $false
    }

    $CreatedVendorLocationIds.Add([string]$location.id) | Out-Null
    return $location
}

function New-UatProduct {
    param(
        [Parameter(Mandatory)][string]$ProductNo,
        [Parameter(Mandatory)]$ReferenceProduct,
        [Parameter(Mandatory)][decimal]$SupplierCost,
        [AllowEmptyString()][string]$VendorLocationCode = ""
    )

    if ([string]::IsNullOrWhiteSpace($VendorLocationCode)) {
        $VendorLocationCode = [string]$ReferenceProduct.vendorLocationCode
    }

    $body = @{
        productNo = $ProductNo
        material = $ReferenceProduct.material
        style = $ReferenceProduct.style
        capacity = [decimal]$ReferenceProduct.capacity
        capacityUom = $ReferenceProduct.capacityUom
        color = $ReferenceProduct.color
        bcItemNo = $ReferenceProduct.bcItemNo
        vendorNo = $ReferenceProduct.vendorNo
        vendorLocationCode = $VendorLocationCode
        transportMode = $ReferenceProduct.transportMode
        fullLoadQuantity = [decimal]$ReferenceProduct.fullLoadQuantity
        noOfPallets = [decimal]$ReferenceProduct.noOfPallets
        gramWeight = [decimal]$ReferenceProduct.gramWeight
        currentSupplierUnitCost = $SupplierCost
        blocked = $false
    }

    $product = Invoke-BcRequest -Method POST -Uri "$UatBase/packagingProductsUAT" -Body $body
    $CreatedProductIds.Add([string]$product.id) | Out-Null
    return $product
}

function New-UatFreightRate {
    param([Parameter(Mandatory)]$ReferenceProduct)

    $rate = Invoke-BcRequest -Method POST -Uri "$UatBase/freightRatesUAT" -Body @{
        originVendorNo = $ReferenceProduct.vendorNo
        originLocationCode = $ReferenceProduct.vendorLocationCode
        destinationState = $DestinationState
        defaultDestination = $false
        mode = $ReferenceProduct.transportMode
        ratePerCwt = 1
        minimumCharge = 100
        fuelSurchargePct = 0
        effectiveDate = (Get-Date).ToString("yyyy-MM-dd")
        notes = $RunId
        blocked = $false
    }

    $CreatedRateIds.Add([string]$rate.id) | Out-Null
    return $rate
}

function New-Comparison {
    $compare = Invoke-BcRequest -Method POST -Uri "$CompareBase/packagingComparisons" -Body @{
        comparisonDate = (Get-Date).ToString("yyyy-MM-dd")
        description = $RunId
        referenceProductNo = $ReferenceProductNo
        destinationState = $DestinationState
        targetGrossMarginPct = 25
        palletCostPerPallet = 10
        tariffPct = 0
        internationalFreightTotal = 0
        customsTotal = 0
        deliveryTotal = 0
    }

    $CreatedCompareIds.Add([string]$compare.id) | Out-Null
    return $compare
}

function Invoke-AddMatching {
    param([Parameter(Mandatory)][string]$CompareId)
    $null = Invoke-BcRequest -Method POST -Uri "$CompareBase/packagingComparisons($CompareId)/Microsoft.NAV.addMatchingCandidates" -Body @{}
}

function Invoke-Calculate {
    param([Parameter(Mandatory)][string]$CompareId)
    $null = Invoke-BcRequest -Method POST -Uri "$CompareBase/packagingComparisons($CompareId)/Microsoft.NAV.calculate" -Body @{}
}

function Get-Comparison {
    param([Parameter(Mandatory)][string]$CompareId)
    return Invoke-BcRequest -Method GET -Uri "$CompareBase/packagingComparisons($CompareId)" -Body $null
}

function Get-ComparisonLines {
    param([Parameter(Mandatory)][int]$CompareEntryNo)

    $filterText = [uri]::EscapeDataString("compareEntryNo eq $CompareEntryNo")
    $response = Invoke-BcRequest -Method GET -Uri "$CompareBase/packagingComparisonLines?`$filter=$filterText" -Body $null
    return @($response.value)
}

try {
    Write-Host ""
    Write-Host "GPI PACKAGING SOURCING COMPARISON API UAT" -ForegroundColor Cyan
    Write-Host "Run ID      : $RunId"
    Write-Host "Environment : $EnvironmentName"
    Write-Host "Reference   : $ReferenceProductNo"
    Write-Host "Destination : $DestinationState"
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
    $CompareBase = "$bcBase/api/gpi/packagingComparisons/v1.0/companies($companyId)"
    $UatBase = "$bcBase/api/gpi/packagingCompareUAT/v1.0/companies($companyId)"

    Write-Host "Company ID  : $companyId"
    Write-Host ""

    $reference = Get-ReferenceProduct
    if (-not $reference) {
        throw "Reference product '$ReferenceProductNo' was not returned by the sandbox UAT API."
    }
    if ([string]::IsNullOrWhiteSpace([string]$reference.vendorNo)) {
        throw "Reference product '$ReferenceProductNo' must have a Vendor No. for comparison UAT."
    }
    if ([string]::IsNullOrWhiteSpace([string]$reference.vendorLocationCode)) {
        throw "Reference product '$ReferenceProductNo' must have a Vendor FOB Location for comparison UAT."
    }
    if ([decimal]$reference.currentSupplierUnitCost -le 0) {
        throw "Reference product '$ReferenceProductNo' must have a positive Current Supplier Unit Cost."
    }

    $productA = "CMPA$Suffix"
    $productB = "CMPB$Suffix"
    $productMissing = "CMPM$Suffix"
    $missingLocationCode = "NR$Suffix"

    $costA = [decimal][math]::Round([double]([decimal]$reference.currentSupplierUnitCost * [decimal]0.50), 5)
    $costB = [decimal][math]::Round([double]([decimal]$reference.currentSupplierUnitCost * [decimal]1.50), 5)
    if ($costA -le 0) { $costA = [decimal]0.01 }
    if ($costB -le $costA) { $costB = $costA + [decimal]0.10 }

    $null = New-UatVendorLocation -ReferenceProduct $reference -LocationCode $missingLocationCode
    $null = New-UatProduct -ProductNo $productA -ReferenceProduct $reference -SupplierCost $costA
    $null = New-UatProduct -ProductNo $productB -ReferenceProduct $reference -SupplierCost $costB
    $null = New-UatProduct -ProductNo $productMissing -ReferenceProduct $reference -SupplierCost $costA -VendorLocationCode $missingLocationCode
    $rate = New-UatFreightRate -ReferenceProduct $reference

    $compare = New-Comparison
    Invoke-AddMatching -CompareId $compare.id
    Invoke-Calculate -CompareId $compare.id

    $compare = Get-Comparison -CompareId $compare.id
    $lines = Get-ComparisonLines -CompareEntryNo ([int]$compare.entryNo)

    $lineA = @($lines | Where-Object { $_.productNo -eq $productA }) | Select-Object -First 1
    $lineB = @($lines | Where-Object { $_.productNo -eq $productB }) | Select-Object -First 1
    $lineMissing = @($lines | Where-Object { $_.productNo -eq $productMissing }) | Select-Object -First 1

    $scenario = "Exact Spec Matching"
    Assert-Equal $scenario "Lower-cost candidate added" ($null -ne $lineA) $true
    Assert-Equal $scenario "Higher-cost candidate added" ($null -ne $lineB) $true
    Assert-Equal $scenario "No-rate candidate added" ($null -ne $lineMissing) $true
    Assert-GreaterOrEqual $scenario "Candidate count" ([decimal]$compare.candidateCount) 3

    if ($lineA -and $lineB) {
        $scenario = "Delivered Cost Ranking"
        Assert-Equal $scenario "Lower-cost candidate rankable" $lineA.isComplete $true
        Assert-Equal $scenario "Higher-cost candidate rankable" $lineB.isComplete $true
        Assert-GreaterThan $scenario "Lower-cost freight rate selected" ([decimal]$lineA.freightRateEntryNo) 0
        Assert-GreaterThan $scenario "Higher-cost freight rate selected" ([decimal]$lineB.freightRateEntryNo) 0
        Assert-DecimalNear $scenario "Lower supplier cost snapshot" ([decimal]$lineA.supplierUnitCost) $costA 0.0001
        Assert-DecimalNear $scenario "Higher supplier cost snapshot" ([decimal]$lineB.supplierUnitCost) $costB 0.0001
        Assert-LessThan $scenario "Lower delivered cost wins" ([decimal]$lineA.landedCostPerUnit) ([decimal]$lineB.landedCostPerUnit)
        Assert-LessThan $scenario "Lower delivered cost has better rank" ([decimal]$lineA.rank) ([decimal]$lineB.rank)
        Assert-GreaterThan $scenario "Suggested sell exceeds landed cost" ([decimal]$lineA.suggestedSellPrice) ([decimal]$lineA.landedCostPerUnit)

        $expectedLandedA = (
            [decimal]$lineA.supplierUnitCost +
            [decimal]$lineA.palletCostPerUnit +
            [decimal]$lineA.domesticFreightPerUnit +
            [decimal]$lineA.tariffPerUnit +
            [decimal]$lineA.internationalFreightPerUnit +
            [decimal]$lineA.customsPerUnit +
            [decimal]$lineA.deliveryPerUnit
        )
        Assert-DecimalNear $scenario "Delivered-cost formula" ([decimal]$lineA.landedCostPerUnit) $expectedLandedA 0.0001
        Assert-GreaterThan $scenario "Higher option has more cost above best" ([decimal]$lineB.costAboveBest) ([decimal]$lineA.costAboveBest)
    }

    if ($lineMissing) {
        $scenario = "Missing Freight Safety"
        Assert-Equal $scenario "No-rate candidate not rankable" $lineMissing.isComplete $false
        Assert-Equal $scenario "No-rate candidate rank" ([int]$lineMissing.rank) 0
        Assert-DecimalNear $scenario "No-rate landed cost not presented" ([decimal]$lineMissing.landedCostPerUnit) 0 0.0001
        Assert-Contains $scenario "Incomplete reason identifies missing rate" $lineMissing.incompleteReason "No active freight rate"
    }

    $scenario = "Comparison Header"
    Assert-GreaterOrEqual $scenario "Ranked count" ([decimal]$compare.rankedCount) 2
    Assert-NotBlank $scenario "Last calculated timestamp" $compare.lastCalculatedAt
    Assert-NotBlank $scenario "Last calculated user" $compare.lastCalculatedBy
    Assert-GreaterThan $scenario "Temporary freight rate created" ([decimal]$rate.entryNo) 0
}
finally {
    if ($CompareBase) {
        foreach ($compareId in $CreatedCompareIds) {
            try {
                $null = Invoke-BcRequest -Method DELETE -Uri "$CompareBase/packagingComparisons($compareId)" -IfMatch -Body $null
            }
            catch {
                Write-Warning "Could not delete UAT comparison $compareId. $($_.Exception.Message)"
            }
        }
    }

    if ($UatBase) {
        foreach ($rateId in $CreatedRateIds) {
            try {
                $null = Invoke-BcRequest -Method DELETE -Uri "$UatBase/freightRatesUAT($rateId)" -IfMatch -Body $null
            }
            catch {
                Write-Warning "Could not delete UAT freight rate $rateId. $($_.Exception.Message)"
            }
        }

        foreach ($productId in $CreatedProductIds) {
            try {
                $null = Invoke-BcRequest -Method DELETE -Uri "$UatBase/packagingProductsUAT($productId)" -IfMatch -Body $null
            }
            catch {
                Write-Warning "Could not delete UAT product $productId. $($_.Exception.Message)"
            }
        }

        foreach ($locationId in $CreatedVendorLocationIds) {
            try {
                $null = Invoke-BcRequest -Method DELETE -Uri "$UatBase/vendorLocationsUAT($locationId)" -IfMatch -Body $null
            }
            catch {
                Write-Warning "Could not delete UAT vendor location $locationId. $($_.Exception.Message)"
            }
        }
    }

    $Secret = $null
    $Token = $null
}

Write-Host ""
Write-Host "COMPARISON UAT RESULTS" -ForegroundColor Cyan
$Results | Format-Table Scenario, Check, Passed, Actual, Expected -AutoSize

$failed = @($Results | Where-Object { -not $_.Passed })
Write-Host ""
Write-Host "Checks run : $($Results.Count)"
Write-Host "Passed     : $($Results.Count - $failed.Count)"
Write-Host "Failed     : $($failed.Count)"
Write-Host "Cleanup    : temporary comparison, candidates, freight rate, and vendor location removed"

if ($failed.Count -gt 0) {
    Write-Host "PACKAGING SOURCING COMPARISON API UAT FAILED" -ForegroundColor Red
    exit 1
}

Write-Host "PACKAGING SOURCING COMPARISON API UAT PASSED" -ForegroundColor Green
exit 0
