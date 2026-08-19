[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DiscoveryFolder,
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [decimal]$MaxUnitCostForPilot = 5.00,
    [switch]$Execute,
    [switch]$Cleanup
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($Execute -and $Cleanup) {
    throw 'Specify either -Execute or -Cleanup, not both.'
}

$eligiblePath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_AutoSeed_Eligible.csv'
$validationPath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Seed_Safety_Validation.csv'
$planPath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Pilot_V2_Plan.csv'
$manifestPath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Pilot_V2_Manifest.csv'

if (-not (Test-Path -LiteralPath $eligiblePath)) {
    throw "Auto-seed eligible file was not found: $eligiblePath"
}
if (-not (Test-Path -LiteralPath $validationPath)) {
    throw "Safety validation file was not found: $validationPath"
}

function Convert-ToBoolean {
    param([AllowNull()]$Value)
    if ($null -eq $Value) { return $false }
    return ([string]$Value).Trim() -match '^(?i:true|yes|1)$'
}

function Convert-ToDecimalOrZero {
    param([AllowNull()]$Value)
    $number = 0D
    [void][decimal]::TryParse([string]$Value, [ref]$number)
    return $number
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

$Token = $null
$Secret = $null

function Invoke-BcRequest {
    param(
        [Parameter(Mandatory)][ValidateSet('GET','POST','DELETE')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [AllowNull()]$Body
    )

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = 'application/json'
    }
    if ($Method -eq 'DELETE') {
        $headers['If-Match'] = '*'
    }

    try {
        if ($Method -eq 'DELETE') {
            return Invoke-RestMethod -Method DELETE -Uri $Uri -Headers $headers
        }

        if ($null -eq $Body) {
            return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers
        }

        $json = $Body | ConvertTo-Json -Depth 10 -Compress
        return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -ContentType 'application/json' -Body $json
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

function Connect-GpiBc {
    if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
        throw "Pilot seed writes are restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
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
    $companies = Invoke-BcRequest -Method GET -Uri "$bcBase/api/v2.0/companies" -Body $null
    $company = @($companies.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
    if (-not $company) {
        throw "Company '$CompanyName' was not returned by the Business Central API."
    }

    return [pscustomobject]@{
        CompanyId = [string]$company.id
        ApiBase = "$bcBase/api/gpi/packagingCompareUAT/v1.0/companies($([string]$company.id))"
    }
}

function Select-DiverseRows {
    param(
        [object[]]$Rows,
        [int]$Quota
    )

    $selected = [System.Collections.Generic.List[object]]::new()
    $seenIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $seenVendors = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

    $ordered = @(
        $Rows |
            Sort-Object `
                @{ Expression = { if ([string]::IsNullOrWhiteSpace([string]$_.SupplierMoldNo)) { 1 } else { 0 } } }, `
                @{ Expression = { if ([string]::IsNullOrWhiteSpace([string]$_.GramWeight)) { 1 } else { 0 } } }, `
                @{ Expression = { Convert-ToDecimalOrZero $_.CurrentSupplierUnitCost } }, `
                GamerID
    )

    foreach ($row in $ordered) {
        if ($selected.Count -ge $Quota) { break }
        $vendor = [string]$row.VendorNo
        if ([string]::IsNullOrWhiteSpace($vendor)) { continue }
        if ($seenVendors.Add($vendor)) {
            $selected.Add($row) | Out-Null
            [void]$seenIds.Add([string]$row.GamerID)
        }
    }

    foreach ($row in $ordered) {
        if ($selected.Count -ge $Quota) { break }
        $id = [string]$row.GamerID
        if ($seenIds.Add($id)) {
            $selected.Add($row) | Out-Null
        }
    }

    return @($selected)
}

$eligible = @(Import-Csv -LiteralPath $eligiblePath)
$validation = @(Import-Csv -LiteralPath $validationPath)

$safeIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($row in $validation) {
    if (Convert-ToBoolean $row.SafeForPilotSeed) {
        [void]$safeIds.Add([string]$row.GamerID)
    }
}

$trustedCategories = @('BOTTLE','JAR','CAN','CANEND')
$safeSource = @(
    $eligible |
        Where-Object {
            $safeIds.Contains([string]$_.GamerID) -and
            ([string]$_.Confidence -eq 'High') -and
            ($trustedCategories -contains ([string]$_.ItemCategoryCode).ToUpperInvariant()) -and
            (Convert-ToDecimalOrZero $_.CurrentSupplierUnitCost) -gt 0 -and
            (Convert-ToDecimalOrZero $_.CurrentSupplierUnitCost) -le $MaxUnitCostForPilot
        }
)

$quotas = [ordered]@{
    BOTTLE = 8
    JAR = 7
    CAN = 6
    CANEND = 4
}

$selected = [System.Collections.Generic.List[object]]::new()
foreach ($category in $quotas.Keys) {
    $quota = [int]$quotas[$category]
    $categoryRows = @($safeSource | Where-Object { ([string]$_.ItemCategoryCode).ToUpperInvariant() -eq $category })
    if ($categoryRows.Count -lt $quota) {
        throw "Not enough safe high-confidence $category records for the pilot. Needed $quota, found $($categoryRows.Count)."
    }
    foreach ($row in @(Select-DiverseRows -Rows $categoryRows -Quota $quota)) {
        $selected.Add($row) | Out-Null
    }
}

if ($selected.Count -ne 25) {
    throw "Pilot selection expected 25 records but selected $($selected.Count)."
}

$plan = foreach ($row in $selected) {
    [pscustomobject]@{
        ItemCategoryCode = $row.ItemCategoryCode
        GamerID = $row.GamerID
        BCItemNo = $row.BCItemNo
        VendorNo = $row.VendorNo
        SupplierMoldNo = $row.SupplierMoldNo
        CurrentSupplierUnitCost = $row.CurrentSupplierUnitCost
        Material = $row.Material
        Capacity = $row.Capacity
        CapacityUOM = $row.CapacityUOM
        Finish = $row.Finish
        FinishType = $row.FinishType
        Color = $row.Color
        Style = $row.Style
        Packout = $row.Packout
        GramWeight = $row.GramWeight
        Description = $row.Description
    }
}
$plan | Export-Csv -LiteralPath $planPath -NoTypeInformation -Encoding UTF8

Write-Host ''
Write-Host 'GPI PACKAGING CATALOG PILOT SEED V2' -ForegroundColor Cyan
Write-Host "Environment        : $EnvironmentName"
Write-Host "Discovery folder   : $DiscoveryFolder"
Write-Host "Trusted categories : $($trustedCategories -join ', ')"
Write-Host "Safe source rows   : $($safeSource.Count)"
Write-Host "Pilot rows         : $($selected.Count)"
Write-Host "Max pilot unit cost: $MaxUnitCostForPilot"
Write-Host ''
Write-Host 'PILOT PLAN V2' -ForegroundColor Cyan
$plan |
    Select-Object ItemCategoryCode, GamerID, VendorNo, CurrentSupplierUnitCost, Material, Capacity, CapacityUOM, Finish, FinishType, Color, Style, GramWeight |
    Format-Table -AutoSize -Wrap
Write-Host "Plan file: $planPath"

if (-not $Execute -and -not $Cleanup) {
    Write-Host ''
    Write-Host 'PREVIEW ONLY. No Business Central data was changed.' -ForegroundColor Green
    Write-Host 'CAP, CROWN, TUBE, BARTOP, and PUMP are intentionally excluded because the current description parser can misclassify positional attributes for those categories.'
    Write-Host 'After reviewing this plan, rerun with -Execute to create only these 25 pilot records in the sandbox.'
    return
}

try {
    $connection = Connect-GpiBc
    $productApi = "$($connection.ApiBase)/packagingProductsUAT"

    if ($Cleanup) {
        if (-not (Test-Path -LiteralPath $manifestPath)) {
            throw "Pilot manifest was not found: $manifestPath"
        }

        $manifest = @(Import-Csv -LiteralPath $manifestPath)
        $createdRows = @($manifest | Where-Object { $_.Status -eq 'Created' -and -not [string]::IsNullOrWhiteSpace([string]$_.Id) })
        Write-Host ''
        Write-Host "Cleaning up $($createdRows.Count) pilot records from the sandbox..." -ForegroundColor Yellow

        foreach ($row in $createdRows) {
            $id = [string]$row.Id
            Invoke-BcRequest -Method DELETE -Uri "$productApi($id)" -Body $null | Out-Null
            Write-Host "Removed $($row.GamerID)" -ForegroundColor DarkGray
        }

        Write-Host 'PILOT V2 CLEANUP COMPLETE' -ForegroundColor Green
        return
    }

    $existing = @(Get-BcPagedCollection -Uri $productApi)
    $existingProductNos = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $existingBcItems = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($row in $existing) {
        if (-not [string]::IsNullOrWhiteSpace([string]$row.productNo)) { [void]$existingProductNos.Add([string]$row.productNo) }
        if (-not [string]::IsNullOrWhiteSpace([string]$row.bcItemNo)) { [void]$existingBcItems.Add([string]$row.bcItemNo) }
    }

    $results = [System.Collections.Generic.List[object]]::new()
    foreach ($row in $selected) {
        $gamerId = [string]$row.GamerID
        $bcItemNo = [string]$row.BCItemNo

        if ($existingProductNos.Contains($gamerId) -or $existingBcItems.Contains($bcItemNo)) {
            $results.Add([pscustomobject]@{
                GamerID = $gamerId
                BCItemNo = $bcItemNo
                Category = $row.ItemCategoryCode
                Status = 'SkippedExisting'
                Id = ''
                Message = 'A catalog product already exists for the Gamer ID or BC Item No.'
            }) | Out-Null
            continue
        }

        $payload = [ordered]@{
            productNo = $gamerId
            supplierMoldNo = [string]$row.SupplierMoldNo
            material = [string]$row.Material
            capacityUom = [string]$row.CapacityUOM
            finish = [string]$row.Finish
            finishType = [string]$row.FinishType
            color = [string]$row.Color
            style = [string]$row.Style
            packout = [string]$row.Packout
            bcItemNo = $bcItemNo
            vendorNo = [string]$row.VendorNo
            currentSupplierUnitCost = (Convert-ToDecimalOrZero $row.CurrentSupplierUnitCost)
            priceChangeNote = 'Milestone 10 pilot V2 seed from BC Item Last Direct Cost; source effective date unknown.'
            blocked = $false
        }

        $capacity = Convert-ToDecimalOrZero $row.Capacity
        if ($capacity -gt 0) { $payload.capacity = $capacity }
        $gramWeight = Convert-ToDecimalOrZero $row.GramWeight
        if ($gramWeight -gt 0) { $payload.gramWeight = $gramWeight }

        try {
            $created = Invoke-BcRequest -Method POST -Uri $productApi -Body $payload
            $results.Add([pscustomobject]@{
                GamerID = $gamerId
                BCItemNo = $bcItemNo
                Category = $row.ItemCategoryCode
                Status = 'Created'
                Id = [string]$created.id
                Message = ''
            }) | Out-Null
            [void]$existingProductNos.Add($gamerId)
            [void]$existingBcItems.Add($bcItemNo)
            $results | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding UTF8
            Write-Host "Created $gamerId" -ForegroundColor DarkGray
        }
        catch {
            $results.Add([pscustomobject]@{
                GamerID = $gamerId
                BCItemNo = $bcItemNo
                Category = $row.ItemCategoryCode
                Status = 'Failed'
                Id = ''
                Message = $_.Exception.Message
            }) | Out-Null
            $results | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding UTF8
            throw
        }
    }

    $results | Export-Csv -LiteralPath $manifestPath -NoTypeInformation -Encoding UTF8
    $createdCount = @($results | Where-Object { $_.Status -eq 'Created' }).Count
    $skippedCount = @($results | Where-Object { $_.Status -eq 'SkippedExisting' }).Count

    Write-Host ''
    Write-Host 'PILOT V2 SEED COMPLETE' -ForegroundColor Green
    Write-Host "Created          : $createdCount"
    Write-Host "Skipped existing : $skippedCount"
    Write-Host "Manifest         : $manifestPath"
    Write-Host ''
    Write-Host 'Only GPI Packaging Product records were created. Existing BC Item records were not modified.'
}
finally {
    $Token = $null
    $Secret = $null
}
