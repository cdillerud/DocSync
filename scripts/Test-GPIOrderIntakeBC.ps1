[CmdletBinding()]
param(
    [ValidateSet('Preflight','LookupDuplicate','WriteRoundTrip')]
    [string]$Mode = 'Preflight',

    [string]$CustomerNumber,
    [string]$ExternalDocumentNumber,
    [string]$ItemNumber,
    [decimal]$Quantity,
    [string]$UnitOfMeasureCode,
    [string]$RequestedDeliveryDate,
    [switch]$Cleanup
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ApprovedEnvironment = 'PRE_GAMERDOCS_CUTOVER_20260831'
$ApprovedCompanyName = 'Gamer Packaging'
$TestPrefix = 'AITEST-'

function Get-RequiredEnv {
    param([Parameter(Mandatory)][string[]]$Names)
    foreach ($name in $Names) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    }
    throw "Required environment variable missing. Tried: $($Names -join ', ')"
}

function Get-BCToken {
    param(
        [Parameter(Mandatory)][string]$TenantId,
        [Parameter(Mandatory)][string]$ClientId,
        [Parameter(Mandatory)][string]$ClientSecret
    )

    $tokenUri = "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token"
    $body = @{
        grant_type    = 'client_credentials'
        client_id     = $ClientId
        client_secret = $ClientSecret
        scope         = 'https://api.businesscentral.dynamics.com/.default'
    }

    $token = Invoke-RestMethod -Method Post -Uri $tokenUri -Body $body -ContentType 'application/x-www-form-urlencoded'
    if (-not $token.access_token) {
        throw 'Business Central token response did not contain access_token.'
    }
    return $token.access_token
}

function Invoke-BCJson {
    param(
        [Parameter(Mandatory)][ValidateSet('GET','POST','DELETE')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][hashtable]$Headers,
        [object]$Body
    )

    if ($Method -eq 'GET') {
        return Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers
    }

    if ($Method -eq 'POST') {
        return Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -Body ($Body | ConvertTo-Json -Depth 20) -ContentType 'application/json'
    }

    Invoke-RestMethod -Method Delete -Uri $Uri -Headers $Headers
}

$tenantId = Get-RequiredEnv -Names @('BC_TENANT_ID','TENANT_ID','BC_SANDBOX_TENANT_ID')
$clientId = Get-RequiredEnv -Names @('BC_CLIENT_ID','BC_SANDBOX_CLIENT_ID')
$clientSecret = Get-RequiredEnv -Names @('BC_CLIENT_SECRET','BC_SANDBOX_CLIENT_SECRET')
$environment = Get-RequiredEnv -Names @('BC_ENVIRONMENT','BC_SANDBOX_ENVIRONMENT')

if ($environment -ne $ApprovedEnvironment) {
    throw "REFUSING TO RUN: this script is restricted to $ApprovedEnvironment. Configured environment: $environment"
}

$token = Get-BCToken -TenantId $tenantId -ClientId $clientId -ClientSecret $clientSecret
$headers = @{
    Authorization = "Bearer $token"
    Accept        = 'application/json'
}

$apiRoot = "https://api.businesscentral.dynamics.com/v2.0/$tenantId/$environment/api/v2.0"
$companies = Invoke-BCJson -Method GET -Uri "$apiRoot/companies" -Headers $headers

$configuredCompanyId = [Environment]::GetEnvironmentVariable('BC_COMPANY_ID')
if (-not [string]::IsNullOrWhiteSpace($configuredCompanyId)) {
    $company = @($companies.value | Where-Object { $_.id -eq $configuredCompanyId })
} else {
    $company = @($companies.value | Where-Object {
        $_.name -eq $ApprovedCompanyName -or $_.displayName -eq $ApprovedCompanyName
    })
}

if ($company.Count -ne 1) {
    throw "Expected exactly one approved company '$ApprovedCompanyName'; found $($company.Count)."
}

$company = $company[0]
$resolvedCompanyName = if ($company.name) { $company.name } else { $company.displayName }
if ($resolvedCompanyName -ne $ApprovedCompanyName) {
    throw "REFUSING TO RUN: resolved company '$resolvedCompanyName' is not '$ApprovedCompanyName'."
}

$companyRoot = "$apiRoot/companies($($company.id))"

Write-Host ('=' * 120)
Write-Host 'GPI ORDER INTAKE BC TEST HARNESS'
Write-Host ('=' * 120)
Write-Host "Environment : $environment"
Write-Host "Company     : $resolvedCompanyName"
Write-Host "Company ID  : $($company.id)"
Write-Host "Mode        : $Mode"
Write-Host 'Release/Post: BLOCKED BY DESIGN'
Write-Host ('=' * 120)

if ($Mode -eq 'Preflight') {
    $result = [ordered]@{
        environment = $environment
        company = $resolvedCompanyName
        companyId = $company.id
        readAccess = 'PASS'
        writeTestFlag = [Environment]::GetEnvironmentVariable('GPI_ORDER_INTAKE_BC_WRITE_TESTS_ENABLED')
        allowedWrites = @('Create tagged Open Sales Order','Create tagged Item lines','Delete tagged Open test Sales Order')
        blocked = @('Release','Ship','Invoice','Post')
    }
    $result | ConvertTo-Json -Depth 10
    exit 0
}

if ([string]::IsNullOrWhiteSpace($CustomerNumber)) {
    throw '-CustomerNumber is required for LookupDuplicate and WriteRoundTrip.'
}

if ($Mode -eq 'LookupDuplicate') {
    if ([string]::IsNullOrWhiteSpace($ExternalDocumentNumber)) {
        throw '-ExternalDocumentNumber is required for LookupDuplicate.'
    }

    $escapedCustomer = $CustomerNumber.Replace("'", "''")
    $escapedExternal = $ExternalDocumentNumber.Replace("'", "''")
    $filter = [Uri]::EscapeDataString("customerNumber eq '$escapedCustomer' and externalDocumentNumber eq '$escapedExternal'")
    $select = [Uri]::EscapeDataString('id,number,customerNumber,customerName,externalDocumentNumber,status,orderDate,requestedDeliveryDate')
    $uri = "$companyRoot/salesOrders?`$select=$select&`$filter=$filter&`$top=20"
    $result = Invoke-BCJson -Method GET -Uri $uri -Headers $headers
    $result.value | ConvertTo-Json -Depth 20
    exit 0
}

if ($Mode -eq 'WriteRoundTrip') {
    $writeFlag = [Environment]::GetEnvironmentVariable('GPI_ORDER_INTAKE_BC_WRITE_TESTS_ENABLED')
    if ($writeFlag -ne 'true') {
        throw 'REFUSING WRITE: set GPI_ORDER_INTAKE_BC_WRITE_TESTS_ENABLED=true explicitly.'
    }
    if ([string]::IsNullOrWhiteSpace($ItemNumber)) {
        throw '-ItemNumber is required for WriteRoundTrip.'
    }
    if ($Quantity -le 0) {
        throw '-Quantity must be greater than zero for WriteRoundTrip.'
    }

    if ([string]::IsNullOrWhiteSpace($ExternalDocumentNumber)) {
        $ExternalDocumentNumber = "$TestPrefix$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    }
    if (-not $ExternalDocumentNumber.StartsWith($TestPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "REFUSING WRITE: test external document number must start with '$TestPrefix'."
    }

    $orderBody = [ordered]@{
        customerNumber = $CustomerNumber
        externalDocumentNumber = $ExternalDocumentNumber
        orderDate = (Get-Date).ToString('yyyy-MM-dd')
    }
    if (-not [string]::IsNullOrWhiteSpace($RequestedDeliveryDate)) {
        $parsed = [datetime]::Parse($RequestedDeliveryDate)
        $orderBody.requestedDeliveryDate = $parsed.ToString('yyyy-MM-dd')
    }

    $createdOrder = $null
    try {
        Write-Host "Creating tagged Open Sales Order: $ExternalDocumentNumber"
        $createdOrder = Invoke-BCJson -Method POST -Uri "$companyRoot/salesOrders" -Headers $headers -Body $orderBody

        $lineBody = [ordered]@{
            lineType = 'Item'
            itemNumber = $ItemNumber
            quantity = $Quantity
        }
        if (-not [string]::IsNullOrWhiteSpace($UnitOfMeasureCode)) {
            $lineBody.unitOfMeasureCode = $UnitOfMeasureCode
        }

        Write-Host "Adding test line: item=$ItemNumber qty=$Quantity"
        $null = Invoke-BCJson -Method POST -Uri "$companyRoot/salesOrders($($createdOrder.id))/salesOrderLines" -Headers $headers -Body $lineBody

        Write-Host 'Reading created order back from BC...'
        $readBack = Invoke-BCJson -Method GET -Uri "$companyRoot/salesOrders($($createdOrder.id))" -Headers $headers
        $lines = Invoke-BCJson -Method GET -Uri "$companyRoot/salesOrders($($createdOrder.id))/salesOrderLines" -Headers $headers

        $output = [ordered]@{
            success = $true
            environment = $environment
            company = $resolvedCompanyName
            salesOrderId = $readBack.id
            salesOrderNumber = $readBack.number
            status = $readBack.status
            customerNumber = $readBack.customerNumber
            externalDocumentNumber = $readBack.externalDocumentNumber
            requestedDeliveryDate = $readBack.requestedDeliveryDate
            lines = $lines.value
            cleanupRequested = [bool]$Cleanup
        }
        $output | ConvertTo-Json -Depth 30

        if ($Cleanup) {
            $current = Invoke-BCJson -Method GET -Uri "$companyRoot/salesOrders($($createdOrder.id))" -Headers $headers
            if (-not ([string]$current.externalDocumentNumber).StartsWith($TestPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw 'REFUSING CLEANUP: order is not tagged as an AITEST order.'
            }
            if ([string]$current.status -notin @('Open','Draft')) {
                throw "REFUSING CLEANUP: test order status is '$($current.status)', not Open/Draft."
            }
            $deleteHeaders = @{
                Authorization = "Bearer $token"
                Accept = 'application/json'
                'If-Match' = '*'
            }
            Write-Host "Deleting tagged test Sales Order $($current.number)..."
            Invoke-BCJson -Method DELETE -Uri "$companyRoot/salesOrders($($createdOrder.id))" -Headers $deleteHeaders
            Write-Host 'Cleanup: PASS'
        }
    }
    catch {
        Write-Error $_
        if ($createdOrder -and $createdOrder.id) {
            Write-Warning "A test order may remain in BC. ID=$($createdOrder.id), Number=$($createdOrder.number), ExternalDocumentNumber=$ExternalDocumentNumber"
        }
        exit 1
    }
}
