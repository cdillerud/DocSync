#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PHASE-0 TARGET + PACKAGE
# =====================================================================================================================
$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$CompanyId         = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'
$EnableFlag        = 'GPI_ORDER_INTAKE_AL_PRE_TEST_ENABLED'

$ExpectedAppId       = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$ExpectedAppName     = 'GPI Order Intake'
$ExpectedPublisher   = 'Gamer Packaging Inc'
$ExpectedAppVersion  = '0.1.0.0'
$ExpectedPackageHash = 'D92A5D2F724F258A690ED0F4E54219A6FE4C9ABCFE3A7FCB731C21E33E266E44'

# One controlled pricing case proven from current Giovanni history.
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

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PackagePath = Join-Path $RepoRoot 'order-intake-bc\.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.0.app'

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

function Invoke-BcJson {
    param(
        [Parameter(Mandatory)][ValidateSet('POST','DELETE')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][hashtable]$Headers,
        [object]$Body
    )
    Assert-BcUri $Uri
    if ($Method -eq 'POST') {
        if ($null -eq $Body) {
            return Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -ContentType 'application/json' -TimeoutSec 90
        }
        return Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -Body ($Body | ConvertTo-Json -Depth 20) -ContentType 'application/json' -TimeoutSec 90
    }
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
    $response = Invoke-BcGet -Uri "$standardCompanyRoot/salesOrders?`$filter=$filter&`$top=5" -Headers $headers
    @($response.value)
}

# ---------------------------------------------------------------------------------------------------------------------
# Local fail-closed preflight.
# ---------------------------------------------------------------------------------------------------------------------
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }
if ([Environment]::GetEnvironmentVariable($EnableFlag) -ine 'true') {
    throw "REFUSING PUBLISH/TEST: set `$env:$EnableFlag = 'true' explicitly for this PRE-only run."
}
if (-not (Test-Path $PackagePath)) { throw "Compiled package not found: $PackagePath" }
$actualHash = (Get-FileHash $PackagePath -Algorithm SHA256).Hash
if ($actualHash -ne $ExpectedPackageHash) {
    throw "Compiled package SHA256 mismatch. Expected $ExpectedPackageHash; got $actualHash. Re-run the compile gate and review before publishing."
}

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

# Server-side environment and company verification before any mutation.
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

$standardCompanyRoot = "$standardRoot/companies($CompanyId)"
$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - PRE AL PUBLISH + ONE CONTROLLED PRICING ROUND-TRIP' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Company ID        : $CompanyId"
Write-Host "App               : $ExpectedAppName $ExpectedAppVersion"
Write-Host "App ID            : $ExpectedAppId"
Write-Host "Package SHA256    : $actualHash"
Write-Host "Customer          : $CustomerNumber"
Write-Host "Item              : $ItemNumber"
Write-Host "Quantity / UOM    : $Quantity $UnitOfMeasureCode"
Write-Host "Location          : $LocationCode / $ExpectedLocationId"
Write-Host "Order Date        : $OrderDate"
Write-Host "Shipment Date     : $ShipmentDate"
Write-Host "Historical Price  : $HistoricalUnitPrice (evidence only; never sent)"
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host 'Release/Ship/Post : NOT IMPLEMENTED / BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

# ---------------------------------------------------------------------------------------------------------------------
# Publish/install PTE only if this exact version is not already installed.
# ---------------------------------------------------------------------------------------------------------------------
$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=200" -Headers $headers
$nameMatches = @($extensions.value | Where-Object {
    [string]$_.displayName -eq $ExpectedAppName -and [string]$_.publisher -eq $ExpectedPublisher
})

$exactInstalled = @($nameMatches | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and
    [int]$_.versionMajor -eq 0 -and [int]$_.versionMinor -eq 1 -and [int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 0 -and
    $_.isInstalled -eq $true
})

if ($exactInstalled.Count -gt 1) { throw 'More than one exact GPI Order Intake 0.1.0.0 installation was returned.' }

if ($exactInstalled.Count -eq 1) {
    Write-Host 'GPI Order Intake 0.1.0.0 is already installed in PRE; skipping duplicate upload.' -ForegroundColor Green
}
else {
    $conflicting = @($nameMatches | Where-Object { [string]$_.id -ne $ExpectedAppId })
    if ($conflicting.Count -gt 0) { throw 'A GPI Order Intake app with an unexpected App ID already exists. Stopping.' }

    Write-Host 'Creating PRE extension-upload record...' -ForegroundColor Yellow
    $uploadRecord = Invoke-BcJson -Method POST -Uri "$automationRoot/extensionUpload" -Headers $headers -Body ([ordered]@{
        schedule = 'Current version'
        schemaSyncMode = 'Add'
    })
    $uploadId = [string]$uploadRecord.systemId
    if ([string]::IsNullOrWhiteSpace($uploadId)) { throw 'extensionUpload did not return systemId.' }

    Write-Host "Uploading vetted package to PRE upload record $uploadId..." -ForegroundColor Yellow
    $contentUri = "$automationRoot/extensionUpload($uploadId)/extensionContent"
    Assert-BcUri $contentUri
    $binaryHeaders = @{ Authorization = "Bearer $token"; Accept = 'application/json'; 'If-Match' = '*' }
    $patch = Invoke-WebRequest -Method Patch -Uri $contentUri -Headers $binaryHeaders -ContentType 'application/octet-stream' -InFile $PackagePath -SkipHttpErrorCheck -TimeoutSec 180
    if ([int]$patch.StatusCode -lt 200 -or [int]$patch.StatusCode -ge 300) {
        throw "Extension content upload failed: HTTP $($patch.StatusCode) $($patch.Content)"
    }

    $deploymentStart = [DateTimeOffset]::UtcNow.AddSeconds(-15)
    Write-Host 'Starting PRE extension deployment...' -ForegroundColor Yellow
    $null = Invoke-BcJson -Method POST -Uri "$automationRoot/extensionUpload($uploadId)/Microsoft.NAV.upload" -Headers $headers

    $completed = $false
    for ($attempt = 1; $attempt -le 90; $attempt++) {
        Start-Sleep -Seconds 2
        $statuses = Invoke-BcGet -Uri "$automationRoot/extensionDeploymentStatus?`$top=200" -Headers $headers
        $matches = @($statuses.value | Where-Object {
            [string]$_.name -eq $ExpectedAppName -and
            [string]$_.publisher -eq $ExpectedPublisher -and
            [string]$_.appVersion -eq $ExpectedAppVersion -and
            ([DateTimeOffset]$_.startedOn) -ge $deploymentStart
        } | Sort-Object { [DateTimeOffset]$_.startedOn } -Descending)

        if ($matches.Count -eq 0) { continue }
        $latest = $matches[0]
        Write-Host "Deployment status: $($latest.status)" -ForegroundColor Yellow
        if ([string]$latest.status -match '(?i)fail|error|cancel') {
            throw "GPI Order Intake deployment failed with status '$($latest.status)'."
        }
        if ([string]$latest.status -match '(?i)complete|success') {
            $completed = $true
            break
        }
    }
    if (-not $completed) { throw 'Timed out waiting for GPI Order Intake deployment to complete.' }
}

# Verify exact installed app after deployment.
$extensionsAfter = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=200" -Headers $headers
$installed = @($extensionsAfter.value | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and [string]$_.displayName -eq $ExpectedAppName -and [string]$_.publisher -eq $ExpectedPublisher -and
    [int]$_.versionMajor -eq 0 -and [int]$_.versionMinor -eq 1 -and [int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 0 -and
    $_.isInstalled -eq $true
})
if ($installed.Count -ne 1) { throw "Post-deployment verification expected one installed $ExpectedAppName $ExpectedAppVersion; found $($installed.Count)." }
Write-Host 'PRE extension install verification: PASS' -ForegroundColor Green

# ---------------------------------------------------------------------------------------------------------------------
# Wait for custom API availability, then execute exactly one AITEST pricing request.
# ---------------------------------------------------------------------------------------------------------------------
$customerFilter = [Uri]::EscapeDataString("number eq '$CustomerNumber'")
$customerUri = "$customRoot/orderIntakeCustomers?`$filter=$customerFilter&`$top=2"
$customerResponse = $null
for ($attempt = 1; $attempt -le 45; $attempt++) {
    try {
        $customerResponse = Invoke-BcGet -Uri $customerUri -Headers $headers
        break
    }
    catch {
        Start-Sleep -Seconds 2
    }
}
if ($null -eq $customerResponse) { throw 'GPI Order Intake custom API did not become available after deployment.' }
$customers = @($customerResponse.value)
if ($customers.Count -ne 1) { throw "Expected exactly one custom-API customer $CustomerNumber; found $($customers.Count)." }
$customerId = [string]$customers[0].id

$external = "$TestPrefix$(Get-Date -Format 'yyyyMMdd-HHmmss')"
if (-not $external.StartsWith('AITEST-', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Generated external document tag failed safety check.' }
if ((Get-TestOrders -ExternalDocumentNumber $external).Count -ne 0) { throw 'Unexpected duplicate test tag before AL action.' }

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

Write-Host "Invoking AL authority with $external..." -ForegroundColor Yellow
$actionResponse = Invoke-WebRequest -Method Post -Uri $actionUri -Headers $headers -ContentType 'application/json' -Body ($actionBody | ConvertTo-Json -Depth 10) -SkipHttpErrorCheck -TimeoutSec 120
$actionStatus = [int]$actionResponse.StatusCode
$actionContent = [string]$actionResponse.Content

$orders = @(Get-TestOrders -ExternalDocumentNumber $external)

if ($actionStatus -lt 200 -or $actionStatus -ge 300) {
    if ($orders.Count -ne 0) {
        throw "AL action returned HTTP $actionStatus but left $($orders.Count) tagged order(s). STOP: manual review required. Response: $actionContent"
    }

    $pricingRollback = $actionContent -match '(?i)pricing validation returned Unit Price\s*0|Unit Price\s*0'
    [ordered]@{
        success = $false
        result = if ($pricingRollback) { 'AL_PRICING_RETURNED_ZERO_AND_TRANSACTION_ROLLED_BACK' } else { 'AL_ACTION_REJECTED_AND_TRANSACTION_ROLLED_BACK' }
        httpStatus = $actionStatus
        environment = $Environment
        company = $CompanyName
        externalDocumentNumber = $external
        residualTaggedOrders = 0
        response = $actionContent
        safety = [ordered]@{
            packageInstalledInPRE = $true
            businessOrderResidual = 'NONE'
            releaseShipInvoicePost = 'NOT IMPLEMENTED / BLOCKED'
            production = 'HARD BLOCKED'
        }
    } | ConvertTo-Json -Depth 20

    if ($pricingRollback) {
        Write-Host 'AL authority price gate returned zero and rolled the draft transaction back: SAFETY PASS / PRICING STILL UNRESOLVED.' -ForegroundColor Yellow
        exit 0
    }
    throw 'AL authority rejected the request for a non-price reason. See response above.'
}

if ($orders.Count -ne 1) { throw "AL action succeeded but expected exactly one tagged Sales Order; found $($orders.Count)." }
$order = $orders[0]
if ([string]$order.customerNumber -ne $CustomerNumber) { throw 'Created order customer mismatch.' }
if ([string]$order.externalDocumentNumber -ne $external) { throw 'Created order external document mismatch.' }
if ([string]$order.status -notin @('Open','Draft')) { throw "Created order status '$($order.status)' is not Open/Draft." }

$linesResponse = Invoke-BcGet -Uri "$standardCompanyRoot/salesOrders($($order.id))/salesOrderLines" -Headers $headers
$lines = @($linesResponse.value | Where-Object { [string]$_.lineType -eq 'Item' -or [string]$_.lineObjectNumber -eq $ItemNumber })
if ($lines.Count -ne 1) { throw "Expected exactly one item line; found $($lines.Count)." }
$line = $lines[0]

if ([string]$line.lineObjectNumber -ne $ItemNumber) { throw 'Created line item mismatch.' }
if ([decimal]$line.quantity -ne $Quantity) { throw "Created line quantity mismatch: $($line.quantity)." }
if ([string]$line.unitOfMeasureCode -ne $UnitOfMeasureCode) { throw "Created line UOM mismatch: $($line.unitOfMeasureCode)." }
if ([string]$line.locationId -ne $ExpectedLocationId) { throw "Created line location mismatch: $($line.locationId)." }
$observedPrice = [decimal]$line.unitPrice
if ($observedPrice -le 0) { throw 'AL action succeeded but read-back Unit Price is zero/nonpositive. Refusing to treat as success.' }

$pricingResult = if ([math]::Abs([double]($observedPrice - $HistoricalUnitPrice)) -lt 0.005) {
    'MATCHED_HISTORICAL_LOCATION_PRICE'
} else {
    'NONZERO_BC_AUTHORITY_PRICE_DIFFERENT_FROM_HISTORICAL_SAMPLE'
}

[ordered]@{
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
        releaseShipInvoicePost = 'NOT IMPLEMENTED / BLOCKED'
        production = 'HARD BLOCKED'
    }
} | ConvertTo-Json -Depth 20

# Mandatory cleanup of only this tagged Draft/Open order.
$current = Invoke-BcGet -Uri "$standardCompanyRoot/salesOrders($($order.id))" -Headers $headers
if (-not ([string]$current.externalDocumentNumber).StartsWith('AITEST-', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'REFUSING CLEANUP: order lost AITEST tag.'
}
if ([string]$current.externalDocumentNumber -ne $external -or [string]$current.customerNumber -ne $CustomerNumber) {
    throw 'REFUSING CLEANUP: tagged order identity changed.'
}
if ([string]$current.status -notin @('Open','Draft')) {
    throw "REFUSING CLEANUP: order status '$($current.status)' is not Open/Draft."
}

$deleteHeaders = @{ Authorization = "Bearer $token"; Accept = 'application/json'; 'If-Match' = '*' }
Write-Host "Deleting tagged test Sales Order $($current.number)..." -ForegroundColor Yellow
Invoke-BcJson -Method DELETE -Uri "$standardCompanyRoot/salesOrders($($order.id))" -Headers $deleteHeaders

$residual = @(Get-TestOrders -ExternalDocumentNumber $external)
if ($residual.Count -ne 0) { throw "Cleanup verification failed: $($residual.Count) tagged order(s) remain." }
Write-Host 'Cleanup: PASS' -ForegroundColor Green
Write-Host 'GPI ORDER INTAKE AL AUTHORITY ROUND-TRIP: PASS' -ForegroundColor Green
