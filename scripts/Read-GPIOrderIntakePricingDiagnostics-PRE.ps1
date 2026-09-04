#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY / GET-ONLY PRICING DIAGNOSTICS
# =====================================================================================================================
$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$CompanyId         = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'

$ExpectedAppId      = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$ExpectedAppName    = 'GPI Order Intake'
$ExpectedPublisher  = 'Gamer Packaging Inc'
$ExpectedAppVersion = '0.1.0.1'

$CustomerNumber = 'GIOVANN'
$ItemNumber     = 'C-503003-12033922'
$Quantity       = [decimal]56.42
$UomCode        = 'M'
$LocationCode   = '00'
$EvidencePrice  = [decimal]277.99
$EvidenceDate   = [datetime]'2026-09-01'

function Convert-TokenToString {
    param([Parameter(Mandatory)]$TokenValue)
    if ($TokenValue -is [string]) { return $TokenValue }
    if ($TokenValue -is [Security.SecureString]) {
        return [System.Net.NetworkCredential]::new('', $TokenValue).Password
    }
    if ($TokenValue.PSObject.Properties.Name -contains 'SecurePassword') {
        return [System.Net.NetworkCredential]::new('', $TokenValue.SecurePassword).Password
    }
    return [string]$TokenValue
}

function Get-BcToken {
    if (-not (Get-Module -ListAvailable -Name Az.Accounts)) {
        throw 'Az.Accounts is required.'
    }
    Import-Module Az.Accounts -ErrorAction Stop

    try {
        $tokenResult = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
        $token = Convert-TokenToString $tokenResult.Token
        if (-not [string]::IsNullOrWhiteSpace($token)) { return $token }
    }
    catch {
        # Fall through to isolated BC-scoped sign-in.
    }

    Write-Host 'Starting Business Central scoped Microsoft sign-in...' -ForegroundColor Yellow
    Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null
    Connect-AzAccount -Tenant $TenantId -AuthScope 'https://api.businesscentral.dynamics.com' -Scope Process -ErrorAction Stop | Out-Null
    $tokenResult = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
    $token = Convert-TokenToString $tokenResult.Token
    if ([string]::IsNullOrWhiteSpace($token)) { throw 'Could not acquire Business Central access token.' }
    return $token
}

function Assert-BcUri {
    param([Parameter(Mandatory)][string]$Uri)
    $parsed = [Uri]$Uri
    if ($parsed.Scheme -ne 'https' -or $parsed.Host -ne 'api.businesscentral.dynamics.com') {
        throw "Unexpected Business Central URI blocked: $Uri"
    }
    if ($Uri.IndexOf($ForbiddenEnv, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Forbidden legacy sandbox URI blocked: $Uri"
    }
    if ($Uri.IndexOf('/Production/', [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Production-like URI blocked: $Uri"
    }
}

function Invoke-BcGet {
    param([Parameter(Mandatory)][string]$Uri, [Parameter(Mandatory)][hashtable]$Headers)
    Assert-BcUri $Uri
    Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 90
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    $Value.Replace("'", "''")
}

function Get-UniqueById {
    param([AllowEmptyCollection()][object[]]$Rows = @())
    $seen = @{}
    $result = foreach ($row in $Rows) {
        $key = [string]$row.id
        if ([string]::IsNullOrWhiteSpace($key)) {
            $key = ([string]$row.priceListCode) + '|' + ([string]$row.lineNumber) + '|' + ([string]$row.sourceType) + '|' + ([string]$row.sourceNumber) + '|' + ([string]$row.assetNumber) + '|' + ([string]$row.productNumber)
        }
        if (-not $seen.ContainsKey($key)) {
            $seen[$key] = $true
            $row
        }
    }
    @($result)
}

# ---------------------------------------------------------------------------------------------------------------------
# Fail-closed constants. This script contains GET only.
# ---------------------------------------------------------------------------------------------------------------------
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

# Server-side environment/company verification.
$environmentResponse = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $headers
$environmentMatches = @($environmentResponse.value | Where-Object { [string]$_.name -eq $Environment })
if ($environmentMatches.Count -ne 1) { throw "Expected exactly one $Environment environment; found $($environmentMatches.Count)." }
$environmentType = [string]$environmentMatches[0].type
if ($environmentType -ine 'sandbox') { throw "SAFETY STOP: $Environment is type '$environmentType', not sandbox." }

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet -Uri "$standardRoot/companies" -Headers $headers
$companyMatches = @($companies.value | Where-Object {
    [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatches.Count -ne 1) { throw "Exact Gamer Packaging company verification failed; found $($companyMatches.Count)." }

$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"

# Verify diagnostics extension version. GET only.
$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=200" -Headers $headers
$installed = @($extensions.value | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and
    [string]$_.displayName -eq $ExpectedAppName -and
    [string]$_.publisher -eq $ExpectedPublisher -and
    [int]$_.versionMajor -eq 0 -and [int]$_.versionMinor -eq 1 -and [int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 1 -and
    $_.isInstalled -eq $true
})
if ($installed.Count -ne 1) { throw "Expected exactly one installed $ExpectedAppName $ExpectedAppVersion; found $($installed.Count)." }

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - PRE PRICING DIAGNOSTICS RESUME / GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Company ID        : $CompanyId"
Write-Host "Installed app     : $ExpectedAppName $ExpectedAppVersion"
Write-Host "Customer          : $CustomerNumber"
Write-Host "Item              : $ItemNumber"
Write-Host "Evidence          : $Quantity $UomCode / location $LocationCode / price $EvidencePrice"
Write-Host 'Extension mutation: NONE' -ForegroundColor Green
Write-Host 'Sales-order action: NOT CALLED' -ForegroundColor Green
Write-Host 'Business data writes: NONE' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

# Customer pricing context.
$customerLiteral = Escape-ODataLiteral $CustomerNumber
$customerFilter = [Uri]::EscapeDataString("number eq '$customerLiteral'")
$customerResponse = Invoke-BcGet -Uri "$customRoot/orderIntakeCustomers?`$filter=$customerFilter&`$top=2" -Headers $headers
$customers = @($customerResponse.value)
if ($customers.Count -ne 1) { throw "Expected exactly one diagnostics customer $CustomerNumber; found $($customers.Count)." }
$customer = $customers[0]

# Existing open Sales Lines for this item. The custom API is read-only.
$itemLiteral = Escape-ODataLiteral $ItemNumber
$lineFilter = [Uri]::EscapeDataString("itemNumber eq '$itemLiteral'")
$openLinesResponse = Invoke-BcGet -Uri "$customRoot/orderIntakeLines?`$filter=$lineFilter&`$top=500" -Headers $headers
$openLines = @($openLinesResponse.value)

# IMPORTANT: Business Central OData does not support OR across distinct fields.
# Query each field independently and merge locally.
$assetFilter = [Uri]::EscapeDataString("assetNumber eq '$itemLiteral'")
$productFilter = [Uri]::EscapeDataString("productNumber eq '$itemLiteral'")
$assetResponse = Invoke-BcGet -Uri "$customRoot/orderIntakePriceLines?`$filter=$assetFilter&`$top=500" -Headers $headers
$productResponse = Invoke-BcGet -Uri "$customRoot/orderIntakePriceLines?`$filter=$productFilter&`$top=500" -Headers $headers
$priceLines = Get-UniqueById -Rows @(@($assetResponse.value) + @($productResponse.value))

# Source candidates are hints from the customer record. All matching is LOCAL below.
$sourceCandidates = @($CustomerNumber)
foreach ($candidate in @(
    [string]$customer.billToCustomerNumber,
    [string]$customer.customerPriceGroup,
    [string]$customer.customerDiscountGroup
)) {
    if (-not [string]::IsNullOrWhiteSpace($candidate)) { $sourceCandidates += $candidate }
}
$sourceCandidates = @($sourceCandidates | Sort-Object -Unique)

$relevantPriceLines = @($priceLines | Where-Object {
    $sourceNo = [string]$_.sourceNumber
    $parentSourceNo = [string]$_.parentSourceNumber
    $uom = [string]$_.unitOfMeasureCode
    $minQty = [decimal]$_.minimumQuantity
    $status = [string]$_.status

    $startOk = $true
    if ($null -ne $_.startingDate -and -not [string]::IsNullOrWhiteSpace([string]$_.startingDate)) {
        try { $startOk = ([datetime]$_.startingDate) -le $EvidenceDate } catch { $startOk = $true }
    }
    $endOk = $true
    if ($null -ne $_.endingDate -and -not [string]::IsNullOrWhiteSpace([string]$_.endingDate)) {
        try {
            $endDate = [datetime]$_.endingDate
            if ($endDate.Year -gt 1) { $endOk = $endDate -ge $EvidenceDate }
        } catch { $endOk = $true }
    }

    $sourceOk = ($sourceCandidates -contains $sourceNo) -or ($sourceCandidates -contains $parentSourceNo) -or ([string]::IsNullOrWhiteSpace($sourceNo) -and [string]::IsNullOrWhiteSpace($parentSourceNo))
    $uomOk = [string]::IsNullOrWhiteSpace($uom) -or $uom -eq $UomCode
    $qtyOk = $minQty -le $Quantity
    $statusOk = [string]::IsNullOrWhiteSpace($status) -or $status -match '(?i)active'

    $sourceOk -and $uomOk -and $qtyOk -and $startOk -and $endOk -and $statusOk
})

$exactHistoricalPriceMatches = @($priceLines | Where-Object {
    try { [math]::Abs([double]([decimal]$_.unitPrice - $EvidencePrice)) -lt 0.005 } catch { $false }
})

$currentOpenMatches = @($openLines | Where-Object {
    [string]$_.itemNumber -eq $ItemNumber -and
    [string]$_.unitOfMeasureCode -eq $UomCode -and
    [math]::Abs([double]([decimal]$_.quantity - $Quantity)) -lt 0.0005
})

$result = [ordered]@{
    success = $true
    mode = 'GET_ONLY_PRICING_DIAGNOSTICS'
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    installedAppVersion = $ExpectedAppVersion
    evidence = [ordered]@{
        customerNumber = $CustomerNumber
        itemNumber = $ItemNumber
        quantity = $Quantity
        unitOfMeasureCode = $UomCode
        locationCode = $LocationCode
        historicalUnitPrice = $EvidencePrice
        evidenceDate = $EvidenceDate.ToString('yyyy-MM-dd')
    }
    customerPricingContext = $customer
    sourceCandidates = $sourceCandidates
    openSalesLineMatches = $currentOpenMatches
    itemPriceListLines = $priceLines
    relevantPriceListLines = $relevantPriceLines
    exactHistoricalPriceMatches = $exactHistoricalPriceMatches
    counts = [ordered]@{
        openSalesLinesForItem = @($openLines).Count
        exactOpenLineQuantityUomMatches = @($currentOpenMatches).Count
        priceListLinesForItem = @($priceLines).Count
        relevantPriceListLines = @($relevantPriceLines).Count
        exactHistoricalPriceMatches = @($exactHistoricalPriceMatches).Count
    }
    safety = [ordered]@{
        extensionMutation = 'NONE'
        salesOrderAction = 'NOT CALLED'
        methodsUsed = 'GET ONLY'
        businessDataWrites = 'NONE'
        releaseShipInvoicePost = 'NOT IMPLEMENTED / BLOCKED'
        production = 'HARD BLOCKED'
    }
}

$result | ConvertTo-Json -Depth 30
Write-Host ''
Write-Host 'GPI ORDER INTAKE PRICING DIAGNOSTICS: GET-ONLY PASS' -ForegroundColor Green
