#requires -Version 7.0

[CmdletBinding()]
param(
    [ValidateSet('Preflight','FindCustomer','ResolveItem','LookupDuplicate','WriteRoundTrip')]
    [string]$Mode = 'Preflight',

    [string]$SearchText,
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

# =====================================================================================================================
# CERTIFIED ORDER-INTAKE TEST TARGET ONLY
# =====================================================================================================================
$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$ExpectedCompanyId = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'
$TestPrefix        = 'AITEST-'
$WriteFlagName     = 'GPI_ORDER_INTAKE_BC_WRITE_TESTS_ENABLED'

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

function Assert-CertifiedConfiguration {
    if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') {
        throw 'Tenant hard pin changed. Execution blocked.'
    }
    if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') {
        throw "Unauthorized Business Central environment '$Environment'. Execution blocked."
    }
    if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') {
        throw "Forbidden Business Central environment '$Environment'. Execution blocked."
    }
    if ($CompanyName -ne 'Gamer Packaging') {
        throw 'Company-name hard pin changed. Execution blocked.'
    }
    if ($ExpectedCompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') {
        throw 'Company-ID hard pin changed. Execution blocked.'
    }
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
            -Method Post -Uri $Uri -Headers $Headers `
            -Body ($Body | ConvertTo-Json -Depth 20) `
            -ContentType 'application/json' -TimeoutSec 90
    }
    Invoke-RestMethod -Method Delete -Uri $Uri -Headers $Headers -TimeoutSec 90
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    return $Value.Replace("'", "''")
}

Assert-CertifiedConfiguration
$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

# Server-side verification that the exact named environment still exists and is a sandbox.
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
$company = $companyMatches[0]
$companyRoot = "$apiRoot/companies($ExpectedCompanyId)"

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE BC TEST HARNESS' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment      : $Environment"
Write-Host "Environment type : $environmentType"
Write-Host "Company          : $CompanyName"
Write-Host "Company ID       : $ExpectedCompanyId"
Write-Host "Mode             : $Mode"
Write-Host "Write flag       : $([Environment]::GetEnvironmentVariable($WriteFlagName))"
Write-Host 'Production       : HARD BLOCKED' -ForegroundColor Green
Write-Host 'Release/Ship/Post: NOT IMPLEMENTED / BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

if ($Mode -eq 'Preflight') {
    [ordered]@{
        environment = $Environment
        environmentType = $environmentType
        company = $CompanyName
        companyId = $ExpectedCompanyId
        readAccess = 'PASS'
        writeTestFlag = [Environment]::GetEnvironmentVariable($WriteFlagName)
        allowedWrites = @(
            'Create tagged Open Sales Order',
            'Create tagged Item line',
            'Delete tagged Open/Draft test Sales Order'
        )
        blocked = @('Release','Ship','Invoice','Post','Production')
    } | ConvertTo-Json -Depth 10
    exit 0
}

if ($Mode -eq 'FindCustomer') {
    if ([string]::IsNullOrWhiteSpace($SearchText)) { throw '-SearchText is required for FindCustomer.' }
    $literal = Escape-ODataLiteral $SearchText
    $filter = [Uri]::EscapeDataString("contains(displayName, '$literal')")
    $select = [Uri]::EscapeDataString('id,number,displayName,email,phoneNumber,blocked')
    $result = Invoke-BcJson -Method GET -Uri "$companyRoot/customers?`$select=$select&`$filter=$filter&`$top=25" -Headers $headers
    $result.value | ConvertTo-Json -Depth 20
    exit 0
}

if ($Mode -eq 'ResolveItem') {
    if ([string]::IsNullOrWhiteSpace($ItemNumber)) { throw '-ItemNumber is required for ResolveItem.' }
    $literal = Escape-ODataLiteral $ItemNumber
    $filter = [Uri]::EscapeDataString("number eq '$literal'")
    $select = [Uri]::EscapeDataString('id,number,displayName,type,blocked,baseUnitOfMeasureCode')
    $result = Invoke-BcJson -Method GET -Uri "$companyRoot/items?`$select=$select&`$filter=$filter&`$top=2" -Headers $headers
    $matches = @($result.value)
    if ($matches.Count -ne 1) { throw "Expected exactly one item '$ItemNumber'; found $($matches.Count)." }
    $matches[0] | ConvertTo-Json -Depth 20
    exit 0
}

if ([string]::IsNullOrWhiteSpace($CustomerNumber)) {
    throw '-CustomerNumber is required for LookupDuplicate and WriteRoundTrip.'
}

if ($Mode -eq 'LookupDuplicate') {
    if ([string]::IsNullOrWhiteSpace($ExternalDocumentNumber)) { throw '-ExternalDocumentNumber is required for LookupDuplicate.' }
    $escapedCustomer = Escape-ODataLiteral $CustomerNumber
    $escapedExternal = Escape-ODataLiteral $ExternalDocumentNumber
    $filter = [Uri]::EscapeDataString("customerNumber eq '$escapedCustomer' and externalDocumentNumber eq '$escapedExternal'")
    $select = [Uri]::EscapeDataString('id,number,customerNumber,customerName,externalDocumentNumber,status,orderDate,requestedDeliveryDate')
    $result = Invoke-BcJson -Method GET -Uri "$companyRoot/salesOrders?`$select=$select&`$filter=$filter&`$top=20" -Headers $headers
    $result.value | ConvertTo-Json -Depth 20
    exit 0
}

if ($Mode -eq 'WriteRoundTrip') {
    $writeFlag = [Environment]::GetEnvironmentVariable($WriteFlagName)
    if ($writeFlag -ine 'true') {
        throw "REFUSING WRITE: set `$env:$WriteFlagName = 'true' explicitly."
    }
    if ([string]::IsNullOrWhiteSpace($ItemNumber)) { throw '-ItemNumber is required for WriteRoundTrip.' }
    if ($Quantity -le 0) { throw '-Quantity must be greater than zero for WriteRoundTrip.' }

    if ([string]::IsNullOrWhiteSpace($ExternalDocumentNumber)) {
        $ExternalDocumentNumber = "$TestPrefix$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    }
    if (-not $ExternalDocumentNumber.StartsWith($TestPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "REFUSING WRITE: external document number must start with '$TestPrefix'."
    }

    # Read-only duplicate protection even for tagged test orders.
    $escapedCustomer = Escape-ODataLiteral $CustomerNumber
    $escapedExternal = Escape-ODataLiteral $ExternalDocumentNumber
    $dupFilter = [Uri]::EscapeDataString("customerNumber eq '$escapedCustomer' and externalDocumentNumber eq '$escapedExternal'")
    $dups = Invoke-BcJson -Method GET -Uri "$companyRoot/salesOrders?`$filter=$dupFilter&`$top=2" -Headers $headers
    if (@($dups.value).Count -ne 0) {
        throw "REFUSING WRITE: tagged external document '$ExternalDocumentNumber' already exists for $CustomerNumber."
    }

    # Resolve exact BC Item No. -> GUID before creating the line.
    $itemLiteral = Escape-ODataLiteral $ItemNumber
    $itemFilter = [Uri]::EscapeDataString("number eq '$itemLiteral'")
    $itemSelect = [Uri]::EscapeDataString('id,number,displayName,type,blocked,baseUnitOfMeasureCode')
    $itemResult = Invoke-BcJson -Method GET -Uri "$companyRoot/items?`$select=$itemSelect&`$filter=$itemFilter&`$top=2" -Headers $headers
    $items = @($itemResult.value)
    if ($items.Count -ne 1) { throw "Expected exactly one BC item '$ItemNumber'; found $($items.Count)." }
    $item = $items[0]
    if ($item.blocked -eq $true) { throw "BC item '$ItemNumber' is blocked." }

    $orderBody = [ordered]@{
        customerNumber = $CustomerNumber
        externalDocumentNumber = $ExternalDocumentNumber
        orderDate = (Get-Date).ToString('yyyy-MM-dd')
    }
    if (-not [string]::IsNullOrWhiteSpace($RequestedDeliveryDate)) {
        $orderBody.requestedDeliveryDate = ([datetime]::Parse($RequestedDeliveryDate)).ToString('yyyy-MM-dd')
    }

    $createdOrder = $null
    try {
        Write-Host "Creating tagged Open Sales Order: $ExternalDocumentNumber" -ForegroundColor Yellow
        $createdOrder = Invoke-BcJson -Method POST -Uri "$companyRoot/salesOrders" -Headers $headers -Body $orderBody

        $lineBody = [ordered]@{
            lineType = 'Item'
            itemId = $item.id
            lineObjectNumber = $item.number
            quantity = $Quantity
        }
        if (-not [string]::IsNullOrWhiteSpace($UnitOfMeasureCode)) {
            $lineBody.unitOfMeasureCode = $UnitOfMeasureCode
        }

        Write-Host "Adding test line: item=$($item.number) itemId=$($item.id) qty=$Quantity uom=$UnitOfMeasureCode" -ForegroundColor Yellow
        $null = Invoke-BcJson -Method POST -Uri "$companyRoot/salesOrders($($createdOrder.id))/salesOrderLines" -Headers $headers -Body $lineBody

        Write-Host 'Reading created order back from BC...' -ForegroundColor Yellow
        $readBack = Invoke-BcJson -Method GET -Uri "$companyRoot/salesOrders($($createdOrder.id))" -Headers $headers
        $lines = Invoke-BcJson -Method GET -Uri "$companyRoot/salesOrders($($createdOrder.id))/salesOrderLines" -Headers $headers

        [ordered]@{
            success = $true
            environment = $Environment
            company = $CompanyName
            salesOrderId = $readBack.id
            salesOrderNumber = $readBack.number
            status = $readBack.status
            customerNumber = $readBack.customerNumber
            externalDocumentNumber = $readBack.externalDocumentNumber
            requestedDeliveryDate = $readBack.requestedDeliveryDate
            resolvedItem = $item
            lines = $lines.value
            cleanupRequested = [bool]$Cleanup
        } | ConvertTo-Json -Depth 30

        if ($Cleanup) {
            $current = Invoke-BcJson -Method GET -Uri "$companyRoot/salesOrders($($createdOrder.id))" -Headers $headers
            if (-not ([string]$current.externalDocumentNumber).StartsWith($TestPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw 'REFUSING CLEANUP: order is not tagged as an AITEST order.'
            }
            if ([string]$current.status -notin @('Open','Draft')) {
                throw "REFUSING CLEANUP: status is '$($current.status)', not Open/Draft."
            }
            $deleteHeaders = @{ Authorization = "Bearer $token"; Accept = 'application/json'; 'If-Match' = '*' }
            Write-Host "Deleting tagged test Sales Order $($current.number)..." -ForegroundColor Yellow
            Invoke-BcJson -Method DELETE -Uri "$companyRoot/salesOrders($($createdOrder.id))" -Headers $deleteHeaders
            Write-Host 'Cleanup: PASS' -ForegroundColor Green
        }
    }
    catch {
        Write-Error $_
        if ($createdOrder -and $createdOrder.id) {
            Write-Warning "A tagged test order may remain in BC. ID=$($createdOrder.id), Number=$($createdOrder.number), ExternalDocumentNumber=$ExternalDocumentNumber"
        }
        exit 1
    }
}
