#requires -Version 7.0

[CmdletBinding()]
param(
    [string]$ShipmentDate = '2026-09-08'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# ONE PURPOSE ONLY:
# Prove whether the standard BC v2.0 Sales Order line API calculates Giovanni price
# when the known BC Location + Shipment Date context is supplied and unitPrice is omitted.
# =====================================================================================================================
$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$ExpectedCompanyId = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'
$WriteFlagName     = 'GPI_ORDER_INTAKE_BC_WRITE_TESTS_ENABLED'
$TestPrefix        = 'AITEST-GIOLOC-'

$CustomerNumber            = 'GIOVANN'
$ItemNumber                = 'C-503003-12033922'
$Quantity                  = [decimal]56.42
$UnitOfMeasureCode         = 'M'
$LocationId                = '53ec399a-c4e1-eb11-abff-7c05070e4047'
$ExpectedLocationCode      = '00'
$ExpectedLocationName      = 'Drop Ship Location'
$HistoricalSampleUnitPrice = [decimal]277.99

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
        throw 'Az.Accounts is required. Install-Module Az.Accounts -Scope CurrentUser'
    }
    Import-Module Az.Accounts -ErrorAction Stop

    try {
        $tokenResult = Get-AzAccessToken `
            -TenantId $TenantId `
            -ResourceUrl 'https://api.businesscentral.dynamics.com' `
            -ErrorAction Stop
        $token = Convert-TokenToString $tokenResult.Token
        if (-not [string]::IsNullOrWhiteSpace($token)) { return $token }
    }
    catch {
        # Fall through to isolated interactive BC-scoped auth.
    }

    Write-Host 'Starting Business Central scoped Microsoft sign-in...' -ForegroundColor Yellow
    Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null
    Connect-AzAccount `
        -Tenant $TenantId `
        -AuthScope 'https://api.businesscentral.dynamics.com' `
        -Scope Process `
        -ErrorAction Stop | Out-Null

    $tokenResult = Get-AzAccessToken `
        -TenantId $TenantId `
        -ResourceUrl 'https://api.businesscentral.dynamics.com' `
        -ErrorAction Stop
    $token = Convert-TokenToString $tokenResult.Token
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw 'Could not acquire Business Central access token.'
    }
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

function Invoke-BcJson {
    param(
        [Parameter(Mandatory)][ValidateSet('GET','POST','DELETE')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][hashtable]$Headers,
        [object]$Body
    )

    Assert-BcUri -Uri $Uri

    if ($Method -eq 'GET') {
        return Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 90
    }

    if ($Method -eq 'POST') {
        return Invoke-RestMethod `
            -Method Post `
            -Uri $Uri `
            -Headers $Headers `
            -Body ($Body | ConvertTo-Json -Depth 20) `
            -ContentType 'application/json' `
            -TimeoutSec 90
    }

    Invoke-RestMethod -Method Delete -Uri $Uri -Headers $Headers -TimeoutSec 90
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    return $Value.Replace("'", "''")
}

# ---------------------------------------------------------------------------------------------------------------------
# Hard safety gates.
# ---------------------------------------------------------------------------------------------------------------------
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed. Execution blocked.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed. Execution blocked.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment. Execution blocked.' }
if ($CompanyName -ne 'Gamer Packaging') { throw 'Company hard pin changed. Execution blocked.' }
if ($ExpectedCompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company ID hard pin changed. Execution blocked.' }
if ($CustomerNumber -ne 'GIOVANN') { throw 'Customer hard pin changed. Execution blocked.' }
if ($ItemNumber -ne 'C-503003-12033922') { throw 'Item hard pin changed. Execution blocked.' }
if ($Quantity -ne [decimal]56.42) { throw 'Quantity hard pin changed. Execution blocked.' }
if ($UnitOfMeasureCode -ne 'M') { throw 'UOM hard pin changed. Execution blocked.' }
if ($LocationId -ne '53ec399a-c4e1-eb11-abff-7c05070e4047') { throw 'Location hard pin changed. Execution blocked.' }

$writeFlag = [Environment]::GetEnvironmentVariable($WriteFlagName)
if ($writeFlag -ine 'true') {
    throw "REFUSING WRITE: set `$env:$WriteFlagName = 'true' explicitly."
}

$parsedShipmentDate = [datetime]::Parse($ShipmentDate)
$shipmentDateIso = $parsedShipmentDate.ToString('yyyy-MM-dd')
$externalDocumentNumber = $TestPrefix + (Get-Date -Format 'yyyyMMdd-HHmmss')

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

# Server-side environment verification.
$environmentResponse = Invoke-BcJson `
    -Method GET `
    -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' `
    -Headers $headers

$environmentMatches = @($environmentResponse.value | Where-Object { [string]$_.name -eq $Environment })
if ($environmentMatches.Count -ne 1) {
    throw "Expected exactly one $Environment environment; found $($environmentMatches.Count)."
}
$environmentType = [string]$environmentMatches[0].type
if ($environmentType -ine 'sandbox') {
    throw "SAFETY STOP: $Environment is type '$environmentType', not sandbox."
}

$environmentEncoded = [Uri]::EscapeDataString($Environment)
$apiRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$environmentEncoded/api/v2.0"
$companies = Invoke-BcJson -Method GET -Uri "$apiRoot/companies" -Headers $headers
$companyMatches = @($companies.value | Where-Object {
    [string]$_.id -eq $ExpectedCompanyId -and
    (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatches.Count -ne 1) {
    throw "Expected exact Gamer Packaging company ID $ExpectedCompanyId; found $($companyMatches.Count)."
}
$companyRoot = "$apiRoot/companies($ExpectedCompanyId)"

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - LOCATION-AWARE PRICE ROUND-TRIP' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Company ID        : $ExpectedCompanyId"
Write-Host "Customer          : $CustomerNumber"
Write-Host "Item              : $ItemNumber"
Write-Host "Quantity / UOM    : $Quantity $UnitOfMeasureCode"
Write-Host "Location          : $ExpectedLocationCode / $ExpectedLocationName / $LocationId"
Write-Host "Shipment Date     : $shipmentDateIso"
Write-Host "Historical Price  : $HistoricalSampleUnitPrice (evidence only; NOT sent to BC)"
Write-Host "External Document : $externalDocumentNumber"
Write-Host 'Unit Price payload: OMITTED ON PURPOSE' -ForegroundColor Yellow
Write-Host 'Cleanup           : MANDATORY' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host 'Release/Ship/Post : NOT IMPLEMENTED / BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

# Resolve and verify exact customer.
$customerLiteral = Escape-ODataLiteral $CustomerNumber
$customerFilter = [Uri]::EscapeDataString("number eq '$customerLiteral'")
$customerSelect = [Uri]::EscapeDataString('id,number,displayName,blocked')
$customerResult = Invoke-BcJson -Method GET -Uri "$companyRoot/customers?`$select=$customerSelect&`$filter=$customerFilter&`$top=2" -Headers $headers
$customers = @($customerResult.value)
if ($customers.Count -ne 1) { throw "Expected exactly one customer '$CustomerNumber'; found $($customers.Count)." }
$customer = $customers[0]

# Resolve and verify exact item.
$itemLiteral = Escape-ODataLiteral $ItemNumber
$itemFilter = [Uri]::EscapeDataString("number eq '$itemLiteral'")
$itemSelect = [Uri]::EscapeDataString('id,number,displayName,type,blocked,baseUnitOfMeasureCode')
$itemResult = Invoke-BcJson -Method GET -Uri "$companyRoot/items?`$select=$itemSelect&`$filter=$itemFilter&`$top=2" -Headers $headers
$items = @($itemResult.value)
if ($items.Count -ne 1) { throw "Expected exactly one item '$ItemNumber'; found $($items.Count)." }
$item = $items[0]
if ($item.blocked -eq $true) { throw "BC item '$ItemNumber' is blocked." }

# Resolve and verify exact BC location.
$locationSelect = [Uri]::EscapeDataString('id,code,displayName')
$locationResult = Invoke-BcJson -Method GET -Uri "$companyRoot/locations?`$select=$locationSelect&`$top=200" -Headers $headers
$locationMatches = @($locationResult.value | Where-Object { [string]$_.id -eq $LocationId })
if ($locationMatches.Count -ne 1) { throw "Expected exact BC Location ID $LocationId; found $($locationMatches.Count)." }
$location = $locationMatches[0]
if ([string]$location.code -ne $ExpectedLocationCode) {
    throw "Location ID resolved to unexpected code '$($location.code)'."
}
if ([string]$location.displayName -ne $ExpectedLocationName) {
    throw "Location ID resolved to unexpected name '$($location.displayName)'."
}

# Read-only duplicate guard for the generated AITEST reference.
$externalLiteral = Escape-ODataLiteral $externalDocumentNumber
$dupFilter = [Uri]::EscapeDataString("customerNumber eq '$customerLiteral' and externalDocumentNumber eq '$externalLiteral'")
$dups = Invoke-BcJson -Method GET -Uri "$companyRoot/salesOrders?`$filter=$dupFilter&`$top=2" -Headers $headers
if (@($dups.value).Count -ne 0) {
    throw "REFUSING WRITE: generated test external document '$externalDocumentNumber' already exists."
}

$createdOrder = $null
try {
    $orderBody = [ordered]@{
        customerNumber = $CustomerNumber
        externalDocumentNumber = $externalDocumentNumber
        orderDate = (Get-Date).ToString('yyyy-MM-dd')
    }

    Write-Host "Creating tagged Draft Sales Order $externalDocumentNumber..." -ForegroundColor Yellow
    $createdOrder = Invoke-BcJson -Method POST -Uri "$companyRoot/salesOrders" -Headers $headers -Body $orderBody

    $lineBody = [ordered]@{
        lineType = 'Item'
        itemId = $item.id
        lineObjectNumber = $item.number
        quantity = $Quantity
        unitOfMeasureCode = $UnitOfMeasureCode
        shipmentDate = $shipmentDateIso
        locationId = $LocationId
    }

    # IMPORTANT: unitPrice is intentionally absent. This test asks whether BC's standard
    # API calculates a price when the known transaction context is supplied.
    Write-Host 'Adding location-aware test line with unitPrice OMITTED...' -ForegroundColor Yellow
    $createdLine = Invoke-BcJson `
        -Method POST `
        -Uri "$companyRoot/salesOrders($($createdOrder.id))/salesOrderLines" `
        -Headers $headers `
        -Body $lineBody

    Write-Host 'Reading test order and line back...' -ForegroundColor Yellow
    $readBack = Invoke-BcJson -Method GET -Uri "$companyRoot/salesOrders($($createdOrder.id))" -Headers $headers
    $lineResponse = Invoke-BcJson -Method GET -Uri "$companyRoot/salesOrders($($createdOrder.id))/salesOrderLines" -Headers $headers
    $readLines = @($lineResponse.value)
    if ($readLines.Count -ne 1) {
        throw "Expected one test order line; found $($readLines.Count)."
    }
    $readLine = $readLines[0]

    $observedPrice = [decimal]$readLine.unitPrice
    $priceResult = if ($observedPrice -eq [decimal]0) {
        'ZERO_PRICE_RETURNED'
    }
    elseif ($observedPrice -eq $HistoricalSampleUnitPrice) {
        'MATCHED_HISTORICAL_LOCATION_PRICE'
    }
    else {
        'NONZERO_PRICE_DIFFERENT_FROM_HISTORICAL_SAMPLE'
    }

    [ordered]@{
        success = $true
        environment = $Environment
        environmentType = $environmentType
        company = $CompanyName
        salesOrderNumber = $readBack.number
        salesOrderId = $readBack.id
        status = $readBack.status
        customerNumber = $readBack.customerNumber
        externalDocumentNumber = $readBack.externalDocumentNumber
        itemNumber = $readLine.lineObjectNumber
        quantity = $readLine.quantity
        unitOfMeasureCode = $readLine.unitOfMeasureCode
        shipmentDate = $readLine.shipmentDate
        locationId = $readLine.locationId
        verifiedLocationCode = $location.code
        verifiedLocationName = $location.displayName
        observedUnitPrice = $observedPrice
        historicalSampleUnitPrice = $HistoricalSampleUnitPrice
        unitPriceWasSent = $false
        pricingResult = $priceResult
        safety = [ordered]@{
            taggedTestOrder = $true
            cleanupMandatory = $true
            releaseShipInvoicePost = 'NOT IMPLEMENTED / BLOCKED'
            production = 'HARD BLOCKED'
        }
    } | ConvertTo-Json -Depth 20
}
finally {
    if ($null -ne $createdOrder -and -not [string]::IsNullOrWhiteSpace([string]$createdOrder.id)) {
        $current = Invoke-BcJson -Method GET -Uri "$companyRoot/salesOrders($($createdOrder.id))" -Headers $headers
        $currentExternal = [string]$current.externalDocumentNumber
        $currentStatus = [string]$current.status

        if (-not $currentExternal.StartsWith($TestPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'REFUSING CLEANUP: created order lost the required AITEST-GIOLOC tag.'
        }
        if ($currentStatus -notin @('Open','Draft')) {
            throw "REFUSING CLEANUP: created test order status is '$currentStatus', not Open/Draft."
        }

        $deleteHeaders = @{
            Authorization = "Bearer $token"
            Accept = 'application/json'
            'If-Match' = '*'
        }
        Write-Host "Deleting tagged test Sales Order $($current.number)..." -ForegroundColor Yellow
        Invoke-BcJson -Method DELETE -Uri "$companyRoot/salesOrders($($createdOrder.id))" -Headers $deleteHeaders | Out-Null
        Write-Host 'Cleanup: PASS' -ForegroundColor Green
    }
}
