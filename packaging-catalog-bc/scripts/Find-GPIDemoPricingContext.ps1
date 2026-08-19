[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$BCItemNo = "FG10900B",
    [string]$UomCode = "EA",
    [decimal]$LandedCostPerUnit = 0.09192,
    [int]$MinimumHistoryLines = 3
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
Write-Host "GPI PACKAGING DEMO PRICING CONTEXT DISCOVERY" -ForegroundColor Cyan
Write-Host "Environment      : $EnvironmentName"
Write-Host "BC Item          : $BCItemNo"
Write-Host "UOM              : $UomCode"
Write-Host "Landed cost/unit : $LandedCostPerUnit"
Write-Host "Minimum history  : $MinimumHistoryLines exact posted lines"
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

$filterText = [uri]::EscapeDataString("itemNo eq '$BCItemNo' and unitOfMeasureCode eq '$UomCode'")
$uri = "$histBase/historicalSalesLines?`$filter=$filterText"
$rawRows = Invoke-BcGet -Uri $uri -Token $token

$asOfDate = (Get-Date).Date.AddDays(1).AddTicks(-1)
$rows = @(
    $rawRows |
        Where-Object {
            ([decimal]$_.quantity -gt 0) -and
            ([decimal]$_.unitPrice -gt 0) -and
            ([datetime]$_.postingDate -le $asOfDate)
        }
)

Write-Host "Company ID       : $companyId"
Write-Host "Exact posted rows: $($rows.Count)"
Write-Host ""

if ($rows.Count -eq 0) {
    Write-Host "No positive posted sales history was found for $BCItemNo / $UomCode." -ForegroundColor Yellow
    Write-Host "READ ONLY. No Business Central data was changed."
    exit 0
}

$customerSummaries = [System.Collections.Generic.List[object]]::new()
foreach ($group in ($rows | Group-Object customerNo)) {
    $customerRows = @($group.Group)
    $recentFive = @(
        $customerRows |
            Sort-Object `
                @{ Expression = { [datetime]$_.postingDate }; Descending = $true }, `
                @{ Expression = { [string]$_.invoiceNo }; Descending = $true }, `
                @{ Expression = { [int]$_.lineNo }; Descending = $true } |
            Select-Object -First 5
    )

    $median = Get-Median -Values @($recentFive | ForEach-Object { [decimal]$_.unitPrice })
    $latest = @($customerRows | Sort-Object @{ Expression = { [datetime]$_.postingDate }; Descending = $true } | Select-Object -First 1)[0]

    $below = [decimal][math]::Round([double]($median * [decimal]0.90), 5)
    $within = [decimal][math]::Round([double]($median), 5)
    $above = [decimal][math]::Round([double]($median * [decimal]1.20), 5)

    $customerSummaries.Add([pscustomobject]@{
        CustomerNo = [string]$group.Name
        CustomerName = [string]$latest.customerName
        HistoryLines = $customerRows.Count
        Recent5Median = $median
        LatestDate = ([datetime]$latest.postingDate).ToString('yyyy-MM-dd')
        BelowHistoryTest = $below
        MedianTest = $within
        AboveHistoryTest = $above
        GPAtMedianPct = Get-GrossMarginPct -Cost $LandedCostPerUnit -Sell $within
        Salesperson = [string]$latest.salespersonCode
    }) | Out-Null
}

$qualified = @(
    $customerSummaries |
        Where-Object { $_.HistoryLines -ge $MinimumHistoryLines } |
        Sort-Object @{ Expression = { $_.HistoryLines }; Descending = $true }, @{ Expression = { $_.Recent5Median }; Descending = $true }
)

Write-Host "CUSTOMERS WITH EXACT HISTORY" -ForegroundColor Cyan
$customerSummaries |
    Sort-Object @{ Expression = { $_.HistoryLines }; Descending = $true } |
    Select-Object -First 20 |
    Format-Table CustomerNo, CustomerName, HistoryLines, Recent5Median, LatestDate, GPAtMedianPct, Salesperson -AutoSize

Write-Host ""
if ($qualified.Count -gt 0) {
    Write-Host "DEMO-READY CUSTOMERS ($MinimumHistoryLines+ exact lines)" -ForegroundColor Green
    $qualified |
        Select-Object CustomerNo, CustomerName, HistoryLines, Recent5Median, BelowHistoryTest, MedianTest, AboveHistoryTest, GPAtMedianPct, LatestDate |
        Format-Table -AutoSize

    $recommended = $qualified[0]
    Write-Host ""
    Write-Host "RECOMMENDED FIRST DEMO" -ForegroundColor Green
    Write-Host "Customer No.       : $($recommended.CustomerNo)"
    Write-Host "Customer Name      : $($recommended.CustomerName)"
    Write-Host "Exact history lines: $($recommended.HistoryLines)"
    Write-Host "Recent-5 median    : $($recommended.Recent5Median)"
    Write-Host "Below-history sell : $($recommended.BelowHistoryTest)  (about 10% below median)"
    Write-Host "Median sell        : $($recommended.MedianTest)"
    Write-Host "Above-history sell : $($recommended.AboveHistoryTest)  (about 20% above median)"
    Write-Host "GP at median       : $($recommended.GPAtMedianPct)% using landed cost $LandedCostPerUnit"
}
else {
    Write-Host "No customer has at least $MinimumHistoryLines exact posted lines for $BCItemNo / $UomCode." -ForegroundColor Yellow
    Write-Host "The product can still demonstrate margin and generic guardrails, but customer-history guardrails need another pilot item or a deliberate UAT-only rule."
}

Write-Host ""
Write-Host "READ ONLY. No Business Central data was changed." -ForegroundColor DarkGray
