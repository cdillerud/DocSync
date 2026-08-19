[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DiscoveryFolder,
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$planPath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Pilot_V2_Plan.csv'
$manifestPath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Pilot_V2_Manifest.csv'
$resultPath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Pilot_V2_Verification.csv'

if (-not (Test-Path -LiteralPath $planPath)) {
    throw "Pilot V2 plan was not found: $planPath"
}
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "Pilot V2 manifest was not found: $manifestPath"
}

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
        [Parameter(Mandatory)][string]$Uri
    )

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = 'application/json'
    }

    try {
        return Invoke-RestMethod -Method GET -Uri $Uri -Headers $headers
    }
    catch {
        $detail = Get-ErrorBody -ErrorRecord $_
        throw "Business Central API GET failed: $Uri`n$detail"
    }
}

function Get-BcPagedCollection {
    param([Parameter(Mandatory)][string]$Uri)

    $rows = [System.Collections.Generic.List[object]]::new()
    $next = $Uri

    while (-not [string]::IsNullOrWhiteSpace($next)) {
        $response = Invoke-BcRequest -Uri $next
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

function Convert-ToDecimalOrZero {
    param([AllowNull()]$Value)
    $number = 0D
    [void][decimal]::TryParse([string]$Value, [ref]$number)
    return $number
}

function Test-TextEqual {
    param([AllowNull()]$Expected, [AllowNull()]$Actual)
    return ([string]$Expected).Trim() -eq ([string]$Actual).Trim()
}

function Test-DecimalEqual {
    param(
        [AllowNull()]$Expected,
        [AllowNull()]$Actual,
        [decimal]$Tolerance = 0.00001D
    )

    $expectedValue = Convert-ToDecimalOrZero $Expected
    $actualValue = Convert-ToDecimalOrZero $Actual
    return [math]::Abs($expectedValue - $actualValue) -le $Tolerance
}

function Add-Mismatch {
    param(
        [System.Collections.Generic.List[string]]$List,
        [string]$Field,
        [AllowNull()]$Expected,
        [AllowNull()]$Actual
    )

    $List.Add("$Field expected '$Expected' actual '$Actual'") | Out-Null
}

function Connect-GpiBc {
    if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
        throw "Pilot verification is restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
    }

    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        throw 'Azure CLI (az) is required.'
    }

    $accountJson = & az account show --output json --only-show-errors 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($accountJson | Out-String))) {
        & az login --tenant $TenantId --only-show-errors | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Azure login failed.'
        }
    }

    $script:Secret = (& az keyvault secret show --vault-name $KeyVaultName --name 'bc-client-secret' --query value --output tsv --only-show-errors).Trim()
    if ([string]::IsNullOrWhiteSpace($script:Secret)) {
        throw "Could not retrieve bc-client-secret from Key Vault $KeyVaultName."
    }

    $tokenResponse = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType 'application/x-www-form-urlencoded' -Body @{
        grant_type = 'client_credentials'
        client_id = $ClientId
        client_secret = $script:Secret
        scope = 'https://api.businesscentral.dynamics.com/.default'
    }

    $script:Token = [string]$tokenResponse.access_token
    if ([string]::IsNullOrWhiteSpace($script:Token)) {
        throw 'Microsoft identity platform did not return an access token.'
    }

    $bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
    $companies = Invoke-BcRequest -Uri "$bcBase/api/v2.0/companies"
    $company = @($companies.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
    if (-not $company) {
        throw "Company '$CompanyName' was not returned by the Business Central API."
    }

    $companyId = [string]$company.id
    return [pscustomobject]@{
        ProductApi = "$bcBase/api/gpi/packagingCompareUAT/v1.0/companies($companyId)/packagingProductsUAT"
        DiscoveryApi = "$bcBase/api/gpi/catalogDiscovery/v1.0/companies($companyId)/bcItems"
    }
}

$plan = @(Import-Csv -LiteralPath $planPath)
$manifest = @(Import-Csv -LiteralPath $manifestPath)
$createdManifest = @($manifest | Where-Object { $_.Status -eq 'Created' })

Write-Host ''
Write-Host 'GPI PACKAGING CATALOG PILOT V2 READ-BACK VERIFICATION' -ForegroundColor Cyan
Write-Host "Environment       : $EnvironmentName"
Write-Host "Discovery folder  : $DiscoveryFolder"
Write-Host "Plan rows         : $($plan.Count)"
Write-Host "Manifest created  : $($createdManifest.Count)"
Write-Host ''

try {
    $connection = Connect-GpiBc
    $products = @(Get-BcPagedCollection -Uri $connection.ProductApi)
    $items = @(Get-BcPagedCollection -Uri $connection.DiscoveryApi)

    $productByNo = @{}
    foreach ($product in $products) {
        $key = ([string]$product.productNo).ToUpperInvariant()
        if ($key) { $productByNo[$key] = $product }
    }

    $itemByNo = @{}
    foreach ($item in $items) {
        $key = ([string]$item.itemNo).ToUpperInvariant()
        if ($key) { $itemByNo[$key] = $item }
    }

    $results = [System.Collections.Generic.List[object]]::new()

    foreach ($expected in $plan) {
        $gamerId = [string]$expected.GamerID
        $key = $gamerId.ToUpperInvariant()
        $targetMismatches = [System.Collections.Generic.List[string]]::new()
        $sourceMismatches = [System.Collections.Generic.List[string]]::new()
        $targetFound = $productByNo.ContainsKey($key)
        $sourceFound = $itemByNo.ContainsKey(([string]$expected.BCItemNo).ToUpperInvariant())
        $metricTonChecked = $false
        $metricTonPass = $true
        $metricTonExpected = 0D
        $metricTonActual = 0D

        if ($targetFound) {
            $actual = $productByNo[$key]

            foreach ($comparison in @(
                @{ Field = 'BC Item No.'; Expected = $expected.BCItemNo; Actual = $actual.bcItemNo },
                @{ Field = 'Vendor No.'; Expected = $expected.VendorNo; Actual = $actual.vendorNo },
                @{ Field = 'Supplier Mold No.'; Expected = $expected.SupplierMoldNo; Actual = $actual.supplierMoldNo },
                @{ Field = 'Material'; Expected = $expected.Material; Actual = $actual.material },
                @{ Field = 'Capacity UOM'; Expected = $expected.CapacityUOM; Actual = $actual.capacityUom },
                @{ Field = 'Finish'; Expected = $expected.Finish; Actual = $actual.finish },
                @{ Field = 'Finish Type'; Expected = $expected.FinishType; Actual = $actual.finishType },
                @{ Field = 'Color'; Expected = $expected.Color; Actual = $actual.color },
                @{ Field = 'Style'; Expected = $expected.Style; Actual = $actual.style },
                @{ Field = 'Packout'; Expected = $expected.Packout; Actual = $actual.packout }
            )) {
                if (-not (Test-TextEqual $comparison.Expected $comparison.Actual)) {
                    Add-Mismatch -List $targetMismatches -Field $comparison.Field -Expected $comparison.Expected -Actual $comparison.Actual
                }
            }

            if (-not (Test-DecimalEqual $expected.Capacity $actual.capacity)) {
                Add-Mismatch -List $targetMismatches -Field 'Capacity' -Expected $expected.Capacity -Actual $actual.capacity
            }
            if (-not (Test-DecimalEqual $expected.CurrentSupplierUnitCost $actual.currentSupplierUnitCost)) {
                Add-Mismatch -List $targetMismatches -Field 'Current Supplier Unit Cost' -Expected $expected.CurrentSupplierUnitCost -Actual $actual.currentSupplierUnitCost
            }
            if (-not (Test-DecimalEqual $expected.GramWeight $actual.gramWeight)) {
                Add-Mismatch -List $targetMismatches -Field 'Gram Weight' -Expected $expected.GramWeight -Actual $actual.gramWeight
            }

            $gramWeight = Convert-ToDecimalOrZero $actual.gramWeight
            $unitCost = Convert-ToDecimalOrZero $actual.currentSupplierUnitCost
            if ($gramWeight -gt 0 -and $unitCost -gt 0) {
                $metricTonChecked = $true
                $metricTonExpected = [math]::Round((1000000D / $gramWeight) * $unitCost, 2, [System.MidpointRounding]::AwayFromZero)
                $metricTonActual = Convert-ToDecimalOrZero $actual.metricTonCost
                $metricTonPass = [math]::Abs($metricTonExpected - $metricTonActual) -le 0.01D
                if (-not $metricTonPass) {
                    Add-Mismatch -List $targetMismatches -Field 'Metric Ton Cost' -Expected $metricTonExpected -Actual $metricTonActual
                }
            }
        }
        else {
            $targetMismatches.Add('Packaging Product was not found in the sandbox') | Out-Null
        }

        if ($sourceFound) {
            $source = $itemByNo[([string]$expected.BCItemNo).ToUpperInvariant()]
            if (-not (Test-TextEqual $expected.VendorNo $source.vendorNo)) {
                Add-Mismatch -List $sourceMismatches -Field 'Live Item Vendor No.' -Expected $expected.VendorNo -Actual $source.vendorNo
            }
            if (-not (Test-DecimalEqual $expected.CurrentSupplierUnitCost $source.lastDirectCost)) {
                Add-Mismatch -List $sourceMismatches -Field 'Live Item Last Direct Cost' -Expected $expected.CurrentSupplierUnitCost -Actual $source.lastDirectCost
            }
        }
        else {
            $sourceMismatches.Add('Linked BC Item was not found in the live Item discovery API') | Out-Null
        }

        $results.Add([pscustomobject]@{
            GamerID = $gamerId
            Category = $expected.ItemCategoryCode
            TargetFound = $targetFound
            TargetExactMatch = ($targetMismatches.Count -eq 0)
            SourceFound = $sourceFound
            LiveSourceMatch = ($sourceMismatches.Count -eq 0)
            MetricTonChecked = $metricTonChecked
            MetricTonPass = $metricTonPass
            MetricTonExpected = $metricTonExpected
            MetricTonActual = $metricTonActual
            TargetMismatches = ($targetMismatches -join '; ')
            SourceMismatches = ($sourceMismatches -join '; ')
        }) | Out-Null
    }

    $results | Export-Csv -LiteralPath $resultPath -NoTypeInformation -Encoding UTF8

    $targetFoundCount = @($results | Where-Object { $_.TargetFound }).Count
    $targetMatchCount = @($results | Where-Object { $_.TargetExactMatch }).Count
    $sourceFoundCount = @($results | Where-Object { $_.SourceFound }).Count
    $sourceMatchCount = @($results | Where-Object { $_.LiveSourceMatch }).Count
    $metricTonRows = @($results | Where-Object { $_.MetricTonChecked })
    $metricTonPassCount = @($metricTonRows | Where-Object { $_.MetricTonPass }).Count
    $failedRows = @($results | Where-Object { -not $_.TargetExactMatch -or -not $_.LiveSourceMatch })

    Write-Host 'READ-BACK SUMMARY' -ForegroundColor Cyan
    Write-Host "Target products found  : $targetFoundCount / $($plan.Count)"
    Write-Host "Target exact matches   : $targetMatchCount / $($plan.Count)"
    Write-Host "Live BC Items found    : $sourceFoundCount / $($plan.Count)"
    Write-Host "Live source matches    : $sourceMatchCount / $($plan.Count)"
    Write-Host "Metric ton checks      : $metricTonPassCount / $($metricTonRows.Count)"
    Write-Host "Rows with mismatches   : $($failedRows.Count)"
    Write-Host "Verification file      : $resultPath"
    Write-Host ''

    if ($failedRows.Count -gt 0) {
        Write-Host 'MISMATCHES' -ForegroundColor Yellow
        $failedRows |
            Select-Object GamerID, Category, TargetMismatches, SourceMismatches |
            Format-Table -AutoSize -Wrap
        Write-Host 'PILOT V2 READ-BACK VERIFICATION FAILED' -ForegroundColor Red
    }
    else {
        Write-Host 'PILOT V2 READ-BACK VERIFICATION PASSED' -ForegroundColor Green
        Write-Host 'All 25 sandbox products match the pilot plan and the current linked BC Item vendor/cost source values.'
    }

    Write-Host ''
    Write-Host 'READ ONLY. No Business Central data was changed.'
}
finally {
    $Token = $null
    $Secret = $null
    Remove-Variable tokenResponse -ErrorAction SilentlyContinue
}
