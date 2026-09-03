#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PHASE-0 TARGET ONLY - TESTS ALREADY-INSTALLED GPI ORDER INTAKE APP
# =====================================================================================================================
$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$CompanyId         = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'
$EnableFlag        = 'GPI_ORDER_INTAKE_AL_AUTHORITY_TEST_ENABLED'

$ExpectedAppId      = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$ExpectedAppName    = 'GPI Order Intake'
$ExpectedPublisher  = 'Gamer Packaging Inc'
$ExpectedAppVersion = '0.1.0.0'

# One controlled Giovanni case proven from current PRE history.
$CustomerNumber      = 'GIOVANN'
$ItemNumber          = 'C-503003-12033922'
$Quantity            = [decimal]56.42
$UnitOfMeasureCode   = 'M'
$LocationCode        = '00'
$ExpectedLocationId  = '53ec399a-c4e1-eb11-abff-7c05070e4047'
$OrderDate           = '2026-09-01'
$ShipmentDate        = '2026-09-08'
$HistoricalUnitPrice = [decimal]277.99
$TestPrefix          = 'AITEST-ALAUTH-'

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
        # Fall through to isolated interactive BC-scoped authentication.
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

function Invoke-BcDelete {
    param([Parameter(Mandatory)][string]$Uri, [Parameter(Mandatory)][hashtable]$Headers)
    Assert-BcUri $Uri
    Invoke-RestMethod -Method Delete -Uri $Uri -Headers $Headers -TimeoutSec 90
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    $Value.Replace("'", "''")
}

function Get-TestOrders {
    param([Parameter(Mandatory)][string]$ExternalDocumentNumber)
    $customer = Escape-ODataLiteral $CustomerNumber
    $external = Escape-ODataLiteral $ExternalDocumentNumber
    $filter = [Uri]::EscapeDataString("customerNumber eq '$customer' and externalDocumentNumber eq '$external'")
    $response = Invoke-BcGet -Uri "$script:StandardCompanyRoot/salesOrders?`$filter=$filter&`$top=5" -Headers $script:Headers
    return @($response.value)
}

function Remove-ExactTaggedTestOrders {
    param([Parameter(Mandatory)][string]$ExternalDocumentNumber)

    $matches = @(Get-TestOrders -ExternalDocumentNumber $ExternalDocumentNumber)
    foreach ($order in $matches) {
        if (-not ([string]$order.externalDocumentNumber).StartsWith('AITEST-', [System.StringComparison]::OrdinalIgnoreCase)) {
            throw 'REFUSING CLEANUP: matched order is not AITEST-tagged.'
        }
        if ([string]$order.externalDocumentNumber -ne $ExternalDocumentNumber) {
            throw 'REFUSING CLEANUP: external document identity mismatch.'
        }
        if ([string]$order.customerNumber -ne $CustomerNumber) {
            throw 'REFUSING CLEANUP: customer identity mismatch.'
        }
        if ([string]$order.status -notin @('Open','Draft')) {
            throw "REFUSING CLEANUP: Sales Order $($order.number) status '$($order.status)' is not Open/Draft."
        }

        $deleteHeaders = @{
            Authorization = "Bearer $script:Token"
            Accept = 'application/json'
            'If-Match' = '*'
        }
        Write-Host "Deleting tagged test Sales Order $($order.number)..." -ForegroundColor Yellow
        Invoke-BcDelete -Uri "$script:StandardCompanyRoot/salesOrders($($order.id))" -Headers $deleteHeaders
    }

    $residual = @(Get-TestOrders -ExternalDocumentNumber $ExternalDocumentNumber)
    if ($residual.Count -ne 0) {
        throw "Cleanup verification failed: $($residual.Count) exact tagged order(s) remain."
    }
}

# ---------------------------------------------------------------------------------------------------------------------
# Fail-closed local configuration checks.
# ---------------------------------------------------------------------------------------------------------------------
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }
if ([Environment]::GetEnvironmentVariable($EnableFlag) -ine 'true') {
    throw "REFUSING AL TEST: set `$env:$EnableFlag = 'true' explicitly for this PRE-only run."
}

$script:Token = Get-BcToken
$script:Headers = @{ Authorization = "Bearer $script:Token"; Accept = 'application/json' }

# Server-side environment verification.
$environmentResponse = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $script:Headers
$environmentMatches = @($environmentResponse.value | Where-Object { [string]$_.name -eq $Environment })
if ($environmentMatches.Count -ne 1) { throw "Expected exactly one $Environment environment; found $($environmentMatches.Count)." }
$environmentType = [string]$environmentMatches[0].type
if ($environmentType -ine 'sandbox') { throw "SAFETY STOP: $Environment is type '$environmentType', not sandbox." }

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet -Uri "$standardRoot/companies" -Headers $script:Headers
$companyMatches = @($companies.value | Where-Object {
    [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatches.Count -ne 1) { throw "Exact Gamer Packaging company verification failed; found $($companyMatches.Count)." }

$script:StandardCompanyRoot = "$standardRoot/companies($CompanyId)"
$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"

# Verify exact app is already installed. This script does not upload or install anything.
$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=200" -Headers $script:Headers
$installed = @($extensions.value | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and
    [string]$_.displayName -eq $ExpectedAppName -and
    [string]$_.publisher -eq $ExpectedPublisher -and
    [int]$_.versionMajor -eq 0 -and [int]$_.versionMinor -eq 1 -and
    [int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 0 -and
    $_.isInstalled -eq $true
})
if ($installed.Count -ne 1) {
    throw "Expected exactly one installed $ExpectedAppName $ExpectedAppVersion in PRE; found $($installed.Count). No publish attempted."
}

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - INSTALLED AL AUTHORITY ONE-SHOT TEST' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Company ID        : $CompanyId"
Write-Host "Installed app     : $ExpectedAppName $ExpectedAppVersion"
Write-Host "App ID            : $ExpectedAppId"
Write-Host "Customer          : $CustomerNumber"
Write-Host "Item              : $ItemNumber"
Write-Host "Quantity / UOM    : $Quantity $UnitOfMeasureCode"
Write-Host "Location          : $LocationCode / $ExpectedLocationId"
Write-Host "Order Date        : $OrderDate"
Write-Host "Shipment Date     : $ShipmentDate"
Write-Host "Historical Price  : $HistoricalUnitPrice (evidence only; NOT sent)"
Write-Host 'Publish / install : NONE - ALREADY INSTALLED' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host 'Release/Ship/Post : NOT IMPLEMENTED / BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

# Wait briefly for custom API metadata/runtime visibility.
$customerFilter = [Uri]::EscapeDataString("number eq '$CustomerNumber'")
$customerUri = "$customRoot/orderIntakeCustomers?`$filter=$customerFilter&`$top=2"
$customerResponse = $null
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $customerResponse = Invoke-BcGet -Uri $customerUri -Headers $script:Headers
        break
    }
    catch {
        Start-Sleep -Seconds 2
    }
}
if ($null -eq $customerResponse) { throw 'GPI Order Intake custom API is not available after verified install.' }
$customers = @($customerResponse.value)
if ($customers.Count -ne 1) { throw "Expected exactly one custom-API customer $CustomerNumber; found $($customers.Count)." }
$customerId = [string]$customers[0].id

$external = "$TestPrefix$(Get-Date -Format 'yyyyMMdd-HHmmss')"
if (-not $external.StartsWith('AITEST-', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Generated external document tag failed safety check.' }
$preexisting = @(Get-TestOrders -ExternalDocumentNumber $external)
if ($preexisting.Count -ne 0) { throw "Unexpected duplicate test tag before AL action: $($preexisting.Count)." }

$actionBody = [ordered]@{
    itemNumber = $ItemNumber
    quantity = $Quantity
    unitOfMeasureCode = $UnitOfMeasureCode
    locationCode = $LocationCode
    orderDate = $OrderDate
    shipmentDate = $ShipmentDate
    externalDocumentNumber = $external
}
$actionUri = "$customRoot/orderIntakeCustomers($customerId)/Microsoft.NAV.createValidatedDraft"
Assert-BcUri $actionUri

$actionStatus = 0
$actionContent = ''
$testResult = $null
$cleanupNeeded = $false

try {
    Write-Host "Invoking AL authority with $external..." -ForegroundColor Yellow
    $actionResponse = Invoke-WebRequest -Method Post -Uri $actionUri -Headers $script:Headers -ContentType 'application/json' -Body ($actionBody | ConvertTo-Json -Depth 10) -SkipHttpErrorCheck -TimeoutSec 120
    $actionStatus = [int]$actionResponse.StatusCode
    $actionContent = [string]$actionResponse.Content

    $orders = @(Get-TestOrders -ExternalDocumentNumber $external)
    $cleanupNeeded = $orders.Count -gt 0

    if ($actionStatus -lt 200 -or $actionStatus -ge 300) {
        if ($orders.Count -ne 0) {
            throw "AL action returned HTTP $actionStatus and left $($orders.Count) tagged order(s). Cleanup will be attempted. Response: $actionContent"
        }

        $pricingRollback = $actionContent -match '(?i)pricing validation returned Unit Price\s*0|Unit Price\s*0'
        $testResult = [ordered]@{
            success = $false
            result = if ($pricingRollback) { 'AL_PRICING_RETURNED_ZERO_AND_TRANSACTION_ROLLED_BACK' } else { 'AL_ACTION_REJECTED_AND_TRANSACTION_ROLLED_BACK' }
            httpStatus = $actionStatus
            environment = $Environment
            company = $CompanyName
            externalDocumentNumber = $external
            residualTaggedOrders = 0
            response = $actionContent
            safety = [ordered]@{
                packageAlreadyInstalledInPRE = $true
                publishThisRun = 'NONE'
                businessOrderResidual = 'NONE'
                releaseShipInvoicePost = 'NOT IMPLEMENTED / BLOCKED'
                production = 'HARD BLOCKED'
            }
        }

        $testResult | ConvertTo-Json -Depth 20
        if ($pricingRollback) {
            Write-Host 'AL price gate returned zero and rolled the transaction back: SAFETY PASS / PRICING STILL UNRESOLVED.' -ForegroundColor Yellow
            return
        }
        throw 'AL authority rejected the request for a non-price reason. See response above.'
    }

    if ($orders.Count -ne 1) { throw "AL action succeeded but expected exactly one tagged Sales Order; found $($orders.Count)." }
    $order = $orders[0]
    if ([string]$order.customerNumber -ne $CustomerNumber) { throw 'Created order customer mismatch.' }
    if ([string]$order.externalDocumentNumber -ne $external) { throw 'Created order external document mismatch.' }
    if ([string]$order.status -notin @('Open','Draft')) { throw "Created order status '$($order.status)' is not Open/Draft." }

    $linesResponse = Invoke-BcGet -Uri "$script:StandardCompanyRoot/salesOrders($($order.id))/salesOrderLines" -Headers $script:Headers
    $lines = @($linesResponse.value | Where-Object {
        [string]$_.lineType -eq 'Item' -or [string]$_.lineObjectNumber -eq $ItemNumber
    })
    if ($lines.Count -ne 1) { throw "Expected exactly one item line; found $($lines.Count)." }
    $line = $lines[0]

    if ([string]$line.lineObjectNumber -ne $ItemNumber) { throw 'Created line item mismatch.' }
    if ([decimal]$line.quantity -ne $Quantity) { throw "Created line quantity mismatch: $($line.quantity)." }
    if ([string]$line.unitOfMeasureCode -ne $UnitOfMeasureCode) { throw "Created line UOM mismatch: $($line.unitOfMeasureCode)." }
    if ([string]$line.locationId -ne $ExpectedLocationId) { throw "Created line location mismatch: $($line.locationId)." }

    $observedPrice = [decimal]$line.unitPrice
    if ($observedPrice -le 0) { throw 'AL action succeeded but read-back Unit Price is zero/nonpositive.' }

    $pricingResult = if ([math]::Abs([double]($observedPrice - $HistoricalUnitPrice)) -lt 0.005) {
        'MATCHED_HISTORICAL_LOCATION_PRICE'
    } else {
        'NONZERO_BC_AUTHORITY_PRICE_DIFFERENT_FROM_HISTORICAL_SAMPLE'
    }

    $testResult = [ordered]@{
        success = $true
        result = 'AL_AUTHORITY_CREATED_PRICED_DRAFT'
        pricingResult = $pricingResult
        environment = $Environment
        company = $CompanyName
        salesOrderNumber = $order.number
        salesOrderId = $order.id
        status = $order.status
        externalDocumentNumber = $external
        itemNumber = $line.lineObjectNumber
        quantity = $line.quantity
        unitOfMeasureCode = $line.unitOfMeasureCode
        locationId = $line.locationId
        observedUnitPrice = $observedPrice
        historicalSampleUnitPrice = $HistoricalUnitPrice
        shipmentDate = $line.shipmentDate
        safety = [ordered]@{
            taggedTestOrder = $true
            cleanupMandatory = $true
            publishThisRun = 'NONE'
            releaseShipInvoicePost = 'NOT IMPLEMENTED / BLOCKED'
            production = 'HARD BLOCKED'
        }
    }

    $testResult | ConvertTo-Json -Depth 20
}
finally {
    if ($external) {
        $remaining = @(Get-TestOrders -ExternalDocumentNumber $external)
        if ($remaining.Count -gt 0) {
            Remove-ExactTaggedTestOrders -ExternalDocumentNumber $external
            Write-Host 'Cleanup: PASS' -ForegroundColor Green
        }
        else {
            Write-Host 'Cleanup: NOT NEEDED - no tagged order remained.' -ForegroundColor Green
        }
    }
}

if ($testResult -and $testResult.success -eq $true) {
    Write-Host 'GPI ORDER INTAKE AL AUTHORITY ROUND-TRIP: PASS' -ForegroundColor Green
}
