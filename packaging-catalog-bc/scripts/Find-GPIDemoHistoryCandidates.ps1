[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DiscoveryFolder,
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [int]$MinimumHistoryLines = 3,
    [int]$TopResults = 20
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$planPath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Pilot_V2_Plan.csv'
if (-not (Test-Path -LiteralPath $planPath)) {
    throw "Pilot V2 plan was not found: $planPath"
}

$pilot = @(Import-Csv -LiteralPath $planPath)
if ($pilot.Count -eq 0) {
    throw "Pilot V2 plan is empty: $planPath"
}

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

Write-Host ""
Write-Host "GPI PILOT PRODUCT CUSTOMER-HISTORY DISCOVERY" -ForegroundColor Cyan
Write-Host "Environment      : $EnvironmentName"
Write-Host "Discovery folder : $DiscoveryFolder"
Write-Host "Pilot products   : $($pilot.Count)"
Write-Host "Minimum history  : $MinimumHistoryLines exact customer/item/UOM posted lines"
Write-Host ""

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "This discovery script is restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
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
$histBase = "$bcBase/api/gpi/commercialGuardrails/v1.0/companies($companyId)"
$asOfDate = (Get-Date).Date.AddDays(1).AddTicks(-1)

$allCandidates = [System.Collections.Generic.List[object]]::new()
$productStats = [System.Collections.Generic.List[object]]::new()

foreach ($product in $pilot) {
    $bcItemNo = [string]$product.BCItemNo
    if ([string]::IsNullOrWhiteSpace($bcItemNo)) {
        continue
    }

    Write-Host "Checking $($product.GamerID) / $bcItemNo ..." -ForegroundColor DarkGray

    $filterText = [uri]::EscapeDataString("itemNo eq '$bcItemNo'")
    $uri = "$histBase/historicalSalesLines?`$filter=$filterText"
    $rawRows = Invoke-BcGet -Uri $uri -Token $token
    $rows = @(
        $rawRows |
            Where-Object {
                ([decimal]$_.quantity -gt 0) -and
                ([decimal]$_.unitPrice -gt 0) -and
                ([datetime]$_.postingDate -le $asOfDate)
            }
    )

    $distinctCustomers = @($rows | Select-Object -ExpandProperty customerNo -Unique).Count
    $distinctUoms = @($rows | Select-Object -ExpandProperty unitOfMeasureCode -Unique).Count
    $productStats.Add([pscustomobject]@{
        Category = [string]$product.ItemCategoryCode
        GamerID = [string]$product.GamerID
        BCItemNo = $bcItemNo
        PostedRows = $rows.Count
        Customers = $distinctCustomers
        UOMs = $distinctUoms
    }) | Out-Null

    if ($rows.Count -eq 0) {
        continue
    }

    $groups = $rows | Group-Object customerNo, unitOfMeasureCode
    foreach ($group in $groups) {
        $groupRows = @($group.Group)
        if ($groupRows.Count -lt $MinimumHistoryLines) {
            continue
        }

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
        $customerNo = [string]$latest.customerNo

        $allCandidates.Add([pscustomobject]@{
            Category = [string]$product.ItemCategoryCode
            GamerID = [string]$product.GamerID
            BCItemNo = $bcItemNo
            CustomerNo = $customerNo
            CustomerName = [string]$latest.customerName
            UOM = $uom
            HistoryLines = $groupRows.Count
            Recent5Median = $median
            BelowHistorySell = [decimal][math]::Round([double]($median * [decimal]0.90), 5)
            MedianSell = $median
            AboveHistorySell = [decimal][math]::Round([double]($median * [decimal]1.20), 5)
            LatestDate = ([datetime]$latest.postingDate).ToString('yyyy-MM-dd')
            Salesperson = [string]$latest.salespersonCode
            CurrentSupplierUnitCost = [decimal]$product.CurrentSupplierUnitCost
            IsEA = ($uom -eq 'EA')
        }) | Out-Null
    }
}

Write-Host ""
Write-Host "PILOT PRODUCT HISTORY SUMMARY" -ForegroundColor Cyan
$productStats |
    Sort-Object @{ Expression = { $_.PostedRows }; Descending = $true }, GamerID |
    Format-Table Category, GamerID, BCItemNo, PostedRows, Customers, UOMs -AutoSize

Write-Host ""
if ($allCandidates.Count -eq 0) {
    Write-Host "No pilot product has at least $MinimumHistoryLines exact posted lines for the same customer, item, and UOM." -ForegroundColor Yellow
    Write-Host "Keep Quote 55 for the margin/guardrail workflow. We can demonstrate customer-history behavior with a separate known-history item without adding it to the 25-product catalog, or defer that piece until later."
    Write-Host ""
    Write-Host "READ ONLY. No Business Central data was changed." -ForegroundColor DarkGray
    exit 0
}

$ranked = @(
    $allCandidates |
        Sort-Object `
            @{ Expression = { if ($_.IsEA) { 0 } else { 1 } } }, `
            @{ Expression = { $_.HistoryLines }; Descending = $true }, `
            @{ Expression = { [datetime]$_.LatestDate }; Descending = $true }
)

Write-Host "DEMO-READY CUSTOMER / ITEM / UOM COMBINATIONS" -ForegroundColor Green
$ranked |
    Select-Object -First $TopResults |
    Format-Table Category, GamerID, CustomerNo, CustomerName, UOM, HistoryLines, Recent5Median, BelowHistorySell, AboveHistorySell, LatestDate -AutoSize -Wrap

$recommended = $ranked[0]
Write-Host ""
Write-Host "RECOMMENDED FIRST HISTORY DEMO" -ForegroundColor Green
Write-Host "Gamer ID           : $($recommended.GamerID)"
Write-Host "BC Item            : $($recommended.BCItemNo)"
Write-Host "Category           : $($recommended.Category)"
Write-Host "Customer No.       : $($recommended.CustomerNo)"
Write-Host "Customer Name      : $($recommended.CustomerName)"
Write-Host "UOM                : $($recommended.UOM)"
Write-Host "Exact history lines: $($recommended.HistoryLines)"
Write-Host "Recent-5 median    : $($recommended.Recent5Median)"
Write-Host "Below-history sell : $($recommended.BelowHistorySell)  (about 10% below median)"
Write-Host "Median sell        : $($recommended.MedianSell)"
Write-Host "Above-history sell : $($recommended.AboveHistorySell)  (about 20% above median)"
Write-Host "Latest history date: $($recommended.LatestDate)"
Write-Host ""
Write-Host "For a pure customer-history demo, keep Target Gross Margin % at 0 so the margin rule does not take precedence over the history rule."
Write-Host "READ ONLY. No Business Central data was changed." -ForegroundColor DarkGray
