#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY / GIOVANNI-WIDE / GET-ONLY RESOLVER PROFILER
# No extension mutation. No Sales Order action. No business-data writes.
# =====================================================================================================================
$TenantId     = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment  = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName  = 'Gamer Packaging'
$CompanyId    = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv = 'Sandbox_NoZetadocs_UAT'

$GpiAppId       = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$GpiAppName     = 'GPI Order Intake'
$GpiPublisher   = 'Gamer Packaging Inc'
$GpiVersion     = '0.1.0.6'
$BoyerAppId     = '65994cd5-4d6f-497e-abc0-767b8c392608'
$BoyerAppName   = 'Boyer And Associates Custom Package'
$BoyerPublisher = 'Boyer And Associates'
$BoyerVersion   = '25.0.0.13'
$CustomerNumber = 'GIOVANN'

# Five normal blanket-PO product families plus the known mixed/exception Salsa component.
# ExpectedNormalQuantity is a guardrail candidate from already-proven physical/history evidence, not an AI inference.
# 24oz Pasta is intentionally left null because both 62.062 M and 56.42 M repeat in current history.
$Targets = @(
    [pscustomobject][ordered]@{ product='24oz Pasta';      itemNumber='C-9874-10001833';  role='NORMAL';    expectedNormalQuantity=$null;    expectedUom='M' },
    [pscustomobject][ordered]@{ product='24oz Salsa';      itemNumber='C-503003-12033922'; role='NORMAL';    expectedNormalQuantity=[decimal]56.42;  expectedUom='M' },
    [pscustomobject][ordered]@{ product='16oz Vinegar';    itemNumber='C-8808-12026443';  role='NORMAL';    expectedNormalQuantity=[decimal]78.166; expectedUom='M' },
    [pscustomobject][ordered]@{ product='14oz Pizza';      itemNumber='C-8479-10000229';  role='NORMAL';    expectedNormalQuantity=[decimal]89.775; expectedUom='M' },
    [pscustomobject][ordered]@{ product='16oz Salsa';      itemNumber='C-503004-12033478'; role='NORMAL';    expectedNormalQuantity=[decimal]78.12;  expectedUom='M' },
    [pscustomobject][ordered]@{ product='24oz Salsa mixed';itemNumber='C-8682-12013925';  role='EXCEPTION'; expectedNormalQuantity=[decimal]5.642;  expectedUom='M' }
)

function Convert-TokenToString {
    param([Parameter(Mandatory)]$TokenValue)
    if ($TokenValue -is [string]) { return $TokenValue }
    if ($TokenValue -is [Security.SecureString]) { return [System.Net.NetworkCredential]::new('', $TokenValue).Password }
    if ($TokenValue.PSObject.Properties.Name -contains 'SecurePassword') {
        return [System.Net.NetworkCredential]::new('', $TokenValue.SecurePassword).Password
    }
    return [string]$TokenValue
}

function Get-BcToken {
    if (-not (Get-Module -ListAvailable -Name Az.Accounts)) { throw 'Az.Accounts is required.' }
    Import-Module Az.Accounts -ErrorAction Stop
    try {
        $r = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
        $t = Convert-TokenToString $r.Token
        if (-not [string]::IsNullOrWhiteSpace($t)) { return $t }
    }
    catch {}

    Write-Host 'Starting Business Central scoped Microsoft sign-in...' -ForegroundColor Yellow
    Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null
    Connect-AzAccount -Tenant $TenantId -AuthScope 'https://api.businesscentral.dynamics.com' -Scope Process -ErrorAction Stop | Out-Null
    $r = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
    $t = Convert-TokenToString $r.Token
    if ([string]::IsNullOrWhiteSpace($t)) { throw 'Could not acquire Business Central access token.' }
    return $t
}

function Assert-BcUri {
    param([Parameter(Mandatory)][string]$Uri)
    $u = [Uri]$Uri
    if ($u.Scheme -ne 'https' -or $u.Host -ne 'api.businesscentral.dynamics.com') { throw "Unexpected BC URI blocked: $Uri" }
    if ($Uri.IndexOf($ForbiddenEnv, [StringComparison]::OrdinalIgnoreCase) -ge 0) { throw 'Forbidden legacy sandbox URI blocked.' }
    if ($Uri.IndexOf('/Production/', [StringComparison]::OrdinalIgnoreCase) -ge 0) { throw 'Production URI blocked.' }
}

function Invoke-BcGet {
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers)
    Assert-BcUri $Uri
    Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 90
}

function Get-NextLink {
    param([Parameter(Mandatory)]$Response)
    $p = $Response.PSObject.Properties['@odata.nextLink']
    if ($null -eq $p -or [string]::IsNullOrWhiteSpace([string]$p.Value)) { return $null }
    return [string]$p.Value
}

function Invoke-BcGetAll {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][hashtable]$Headers,
        [ValidateRange(1,20)][int]$MaxPages = 10
    )
    $rows = [System.Collections.Generic.List[object]]::new()
    $next = $Uri
    $page = 0
    while (-not [string]::IsNullOrWhiteSpace($next)) {
        $page++
        if ($page -gt $MaxPages) { throw "GET pagination exceeded $MaxPages pages: $Uri" }
        $response = Invoke-BcGet $next $Headers
        foreach ($row in @($response.value)) { $rows.Add($row) }
        $next = Get-NextLink $response
    }
    return @($rows)
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    $Value.Replace("'", "''")
}

function Get-InstalledVersionString {
    param([Parameter(Mandatory)]$Extension)
    "$($Extension.versionMajor).$($Extension.versionMinor).$($Extension.versionBuild).$($Extension.versionRevision)"
}

function Get-LatestPriceRunLength {
    param([Parameter(Mandatory)][object[]]$Rows)
    if ($Rows.Length -eq 0) { return 0 }
    $sorted = @($Rows | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
    $price = [decimal]$sorted[0].unitPrice
    $count = 0
    foreach ($row in $sorted) {
        if ([decimal]$row.unitPrice -ne $price) { break }
        $count++
    }
    return $count
}

function New-QuantityUomGroups {
    param([Parameter(Mandatory)][object[]]$Rows)
    $output = [System.Collections.Generic.List[object]]::new()
    $groups = @($Rows | Group-Object { ('{0}|{1}' -f ([decimal]$_.quantity), [string]$_.unitOfMeasureCode) })
    foreach ($group in $groups) {
        $gRows = @($group.Group | Sort-Object {[DateTimeOffset]$_.systemCreatedAt})
        $latest = $gRows[-1]
        $locations = @($gRows | ForEach-Object {[string]$_.locationCode} | Sort-Object -Unique)
        $prices = @($gRows | ForEach-Object {[decimal]$_.unitPrice} | Sort-Object -Unique)
        $output.Add([pscustomobject][ordered]@{
            quantity = [decimal]$latest.quantity
            uom = [string]$latest.unitOfMeasureCode
            count = $gRows.Length
            firstCreatedAt = [string]$gRows[0].systemCreatedAt
            latestCreatedAt = [string]$latest.systemCreatedAt
            locations = $locations
            distinctPrices = $prices
        })
    }
    return @($output | Sort-Object count -Descending, quantity -Descending)
}

function New-PriceContexts {
    param([Parameter(Mandatory)][object[]]$Rows)
    $output = [System.Collections.Generic.List[object]]::new()
    $groups = @($Rows | Group-Object { ('{0}|{1}|{2}' -f ([decimal]$_.quantity), [string]$_.unitOfMeasureCode, [string]$_.locationCode) })
    foreach ($group in $groups) {
        $gRows = @($group.Group | Sort-Object {[DateTimeOffset]$_.systemCreatedAt})
        $latest = $gRows[-1]
        $priceGroups = @($gRows | Group-Object { [string]([decimal]$_.unitPrice) } | Sort-Object Count -Descending)
        $priceEvidence = @($priceGroups | ForEach-Object {
            [pscustomobject][ordered]@{ unitPrice=[decimal]$_.Group[0].unitPrice; count=$_.Count }
        })
        $latestRun = Get-LatestPriceRunLength $gRows
        $confidence = if ($latestRun -ge 2) { 'HIGH_LATEST_PRICE_REPEATED' } elseif ($gRows.Length -ge 2 -and $priceGroups.Length -eq 1) { 'HIGH_SINGLE_HISTORICAL_PRICE' } elseif ($gRows.Length -eq 1) { 'LOW_SINGLE_OBSERVATION' } else { 'MEDIUM_LATEST_PRICE_CHANGED' }
        $output.Add([pscustomobject][ordered]@{
            quantity = [decimal]$latest.quantity
            uom = [string]$latest.unitOfMeasureCode
            locationCode = [string]$latest.locationCode
            rowCount = $gRows.Length
            latestDocumentNumber = [string]$latest.documentNumber
            latestCreatedAt = [string]$latest.systemCreatedAt
            latestShipmentDate = [string]$latest.shipmentDate
            latestUnitPrice = [decimal]$latest.unitPrice
            latestUnitCost = [decimal]$latest.unitCost
            latestPriceConsecutiveRunLength = $latestRun
            distinctPriceEvidence = $priceEvidence
            candidateConfidence = $confidence
        })
    }
    return @($output | Sort-Object quantity -Descending, uom, locationCode)
}

function Get-PropertyValue {
    param([Parameter(Mandatory)]$Object,[Parameter(Mandatory)][string]$Name)
    $p = $Object.PSObject.Properties[$Name]
    if ($null -eq $p) { return $null }
    return $p.Value
}

# Fail closed before network access.
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831' -or $Environment -match '(?i)prod|production') { throw 'Environment pin changed/forbidden.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company pin changed.' }
if ($CustomerNumber -ne 'GIOVANN') { throw 'Customer pin changed.' }

$token = Get-BcToken
$headers = @{Authorization="Bearer $token";Accept='application/json'}

$envs = Invoke-BcGet 'https://api.businesscentral.dynamics.com/environments/v1.2' $headers
$envMatch = @($envs.value | Where-Object {[string]$_.name -eq $Environment})
if ($envMatch.Length -ne 1 -or [string]$envMatch[0].type -ine 'sandbox') { throw 'Exact PRE sandbox verification failed.' }
$environmentType = [string]$envMatch[0].type

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet "$standardRoot/companies" $headers
$companyMatch = @($companies.value | Where-Object {[string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))})
if ($companyMatch.Length -ne 1) { throw 'Exact Gamer Packaging company verification failed.' }

$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"
$extensions = Invoke-BcGet "$automationRoot/extensions?`$top=500" $headers
$installed = @($extensions.value | Where-Object {$_.isInstalled -eq $true})
$gpi = @($installed | Where-Object {[string]$_.id -eq $GpiAppId -and [string]$_.displayName -eq $GpiAppName -and [string]$_.publisher -eq $GpiPublisher -and (Get-InstalledVersionString $_) -eq $GpiVersion})
if ($gpi.Length -ne 1) { throw "Expected exactly one installed $GpiAppName $GpiVersion; found $($gpi.Length)." }
$boyer = @($installed | Where-Object {[string]$_.id -eq $BoyerAppId -and [string]$_.displayName -eq $BoyerAppName -and [string]$_.publisher -eq $BoyerPublisher -and (Get-InstalledVersionString $_) -eq $BoyerVersion})
if ($boyer.Length -ne 1) { throw "Expected exactly one installed $BoyerAppName $BoyerVersion; found $($boyer.Length)." }

Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - GIOVANNI RESOLVER PROFILE / PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "Environment        : $Environment"
Write-Host "Environment type   : $environmentType"
Write-Host "Company            : $CompanyName"
Write-Host "GPI Order Intake   : $GpiVersion"
Write-Host "Boyer dependency   : $BoyerVersion"
Write-Host "Customer           : $CustomerNumber"
Write-Host "Target BC items    : $($Targets.Length)"
Write-Host 'HTTP methods       : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation : NONE' -ForegroundColor Green
Write-Host 'Business data write: NONE' -ForegroundColor Green
Write-Host 'Sales-order action : NOT CALLED' -ForegroundColor Green
Write-Host 'Production         : HARD BLOCKED' -ForegroundColor Green
Write-Host ('='*120) -ForegroundColor Cyan

$profiles = [System.Collections.Generic.List[object]]::new()

foreach ($target in $Targets) {
    $itemLiteral = Escape-ODataLiteral ([string]$target.itemNumber)
    $custLiteral = Escape-ODataLiteral $CustomerNumber
    $itemFilter = [Uri]::EscapeDataString("itemNumber eq '$itemLiteral'")
    $custItemFilter = [Uri]::EscapeDataString("sellToCustomerNumber eq '$custLiteral' and itemNumber eq '$itemLiteral'")

    $uoms = @(Invoke-BcGetAll "$customRoot/orderIntakeItemUnitsOfMeasure?`$filter=$itemFilter&`$top=200" $headers)
    $rollingRows = @(Invoke-BcGetAll "$customRoot/orderIntakeCustomerItemSales?`$filter=$custItemFilter&`$top=2" $headers)
    if ($rollingRows.Length -gt 1) { throw "Expected at most one Customer Item Sales row for $CustomerNumber / $($target.itemNumber); found $($rollingRows.Length)." }
    $invoiceRows = @(Invoke-BcGetAll "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$custItemFilter&`$top=500" $headers)
    $openRows = @(Invoke-BcGetAll "$customRoot/orderIntakeLines?`$filter=$custItemFilter&`$top=500" $headers)

    $invoiceRows = @($invoiceRows | Sort-Object {[DateTimeOffset]$_.systemCreatedAt})
    $openRows = @($openRows | Sort-Object {[DateTimeOffset]$_.systemCreatedAt})
    $quantityGroups = @(New-QuantityUomGroups $invoiceRows)
    $priceContexts = @(New-PriceContexts $invoiceRows)

    $expectedQty = $target.expectedNormalQuantity
    $expectedUom = [string]$target.expectedUom
    $expectedRows = if ($null -eq $expectedQty) { @() } else { @($invoiceRows | Where-Object {[decimal]$_.quantity -eq [decimal]$expectedQty -and [string]$_.unitOfMeasureCode -eq $expectedUom}) }
    $expectedContexts = if ($null -eq $expectedQty) { @() } else { @($priceContexts | Where-Object {[decimal]$_.quantity -eq [decimal]$expectedQty -and [string]$_.uom -eq $expectedUom}) }

    $quantityStatus = if ([string]$target.role -eq 'EXCEPTION') {
        if ($expectedRows.Length -ge 1) { 'EXCEPTION_CONTEXT_CONFIRMED' } else { 'REVIEW_EXCEPTION_NOT_FOUND' }
    }
    elseif ($null -eq $expectedQty) {
        $repeatedGroups = @($quantityGroups | Where-Object {$_.count -ge 2})
        if ($repeatedGroups.Length -gt 1) { 'REVIEW_MULTIPLE_REPEATED_QUANTITY_UOM_CONTEXTS' }
        elseif ($repeatedGroups.Length -eq 1) { 'CANDIDATE_SINGLE_REPEATED_QUANTITY_UOM_CONTEXT' }
        else { 'REVIEW_NO_REPEATED_QUANTITY_UOM_CONTEXT' }
    }
    elseif ($expectedRows.Length -ge 2) { 'CONFIRMED_EXPECTED_QUANTITY_UOM' }
    elseif ($expectedRows.Length -eq 1) { 'REVIEW_EXPECTED_QUANTITY_UOM_SINGLE_OBSERVATION' }
    else { 'REVIEW_EXPECTED_QUANTITY_UOM_NOT_FOUND' }

    $latestPricesForExpectedContexts = @($expectedContexts | ForEach-Object {[decimal]$_.latestUnitPrice} | Sort-Object -Unique)
    $expectedLocations = @($expectedContexts | ForEach-Object {[string]$_.locationCode} | Sort-Object -Unique)
    $locationPriceStatus = if ($null -eq $expectedQty) {
        'REVIEW_QUANTITY_CONTEXT_BEFORE_PRICE'
    }
    elseif ($expectedContexts.Length -eq 0) {
        'REVIEW_NO_EXPECTED_PRICE_CONTEXT'
    }
    elseif ($expectedLocations.Length -gt 1 -and $latestPricesForExpectedContexts.Length -gt 1) {
        'LOCATION_REQUIRED_FOR_PRICE'
    }
    elseif ($latestPricesForExpectedContexts.Length -eq 1) {
        'LATEST_PRICE_SAME_ACROSS_OBSERVED_LOCATIONS'
    }
    else {
        'REVIEW_PRICE_CONTEXT'
    }

    $rolling = if ($rollingRows.Length -eq 1) { $rollingRows[0] } else { $null }
    $rollingMatchesExpectedQtyUom = $false
    $rollingMatchesObservedContext = $false
    if ($null -ne $rolling) {
        if ($null -ne $expectedQty) {
            $rollingMatchesExpectedQtyUom = ([decimal]$rolling.lastSoldQuantity -eq [decimal]$expectedQty -and [string]$rolling.lastSoldUnitOfMeasureCode -eq $expectedUom)
        }
        $contextMatch = @($priceContexts | Where-Object {
            [decimal]$_.quantity -eq [decimal]$rolling.lastSoldQuantity -and
            [string]$_.uom -eq [string]$rolling.lastSoldUnitOfMeasureCode -and
            [string]$_.locationCode -eq [string]$rolling.locationCode -and
            [decimal]$_.latestUnitPrice -eq [decimal]$rolling.lastUnitPrice
        })
        $rollingMatchesObservedContext = ($contextMatch.Length -ge 1)
    }

    $resolverDecision = if ([string]$target.role -eq 'EXCEPTION') {
        'REVIEW_EXCEPTION_ONLY_DO_NOT_AUTO_APPLY_TO_NORMAL_ROWS'
    }
    elseif ($quantityStatus -like 'REVIEW*') {
        'REVIEW_QUANTITY_CONTEXT'
    }
    elseif ($locationPriceStatus -eq 'REVIEW_NO_EXPECTED_PRICE_CONTEXT' -or $locationPriceStatus -eq 'REVIEW_PRICE_CONTEXT') {
        'REVIEW_PRICE_CONTEXT'
    }
    elseif ($locationPriceStatus -eq 'LOCATION_REQUIRED_FOR_PRICE') {
        'PASS_WITH_LOCATION_REQUIRED'
    }
    else {
        'PASS_PROFILE_CANDIDATE'
    }

    $profiles.Add([pscustomobject][ordered]@{
        product = [string]$target.product
        itemNumber = [string]$target.itemNumber
        role = [string]$target.role
        expectedNormalQuantity = $expectedQty
        expectedUom = $expectedUom
        postedInvoiceLineCount = $invoiceRows.Length
        openSalesLineCount = $openRows.Length
        itemUnitsOfMeasure = @($uoms | Sort-Object code)
        quantityUomEvidence = $quantityGroups
        priceContextsByQuantityUomLocation = $priceContexts
        currentBoyerCustomerItemSales = $rolling
        rollingMatchesExpectedQtyUom = $rollingMatchesExpectedQtyUom
        rollingMatchesLatestObservedContext = $rollingMatchesObservedContext
        quantityStatus = $quantityStatus
        locationPriceStatus = $locationPriceStatus
        resolverDecision = $resolverDecision
        proposedGuardrail = [ordered]@{
            quantityUom = if ($null -eq $expectedQty) { 'REVIEW - do not infer a single quantity' } else { "$expectedQty $expectedUom" }
            price = 'Use latest posted invoice price for exact customer+item+qty+UOM+location only when context has sufficient evidence; Boyer rolling Last Unit Price is corroboration only.'
            location = if ($locationPriceStatus -eq 'LOCATION_REQUIRED_FOR_PRICE') { 'REQUIRED BEFORE PRICE RESOLUTION' } else { 'Use exact order location when resolving price.' }
            conflict = 'REVIEW on missing, conflicting, single-observation, mixed, partial, reroute or cancellation context.'
        }
    })
}

$normalProfiles = @($profiles | Where-Object {$_.role -eq 'NORMAL'})
$passProfiles = @($normalProfiles | Where-Object {$_.resolverDecision -like 'PASS*'})
$reviewProfiles = @($normalProfiles | Where-Object {$_.resolverDecision -like 'REVIEW*'})

$result = [ordered]@{
    success = $true
    mode = 'PRE_GIOVANNI_WIDE_RESOLVER_PROFILE_GET_ONLY'
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    customer = $CustomerNumber
    gpiOrderIntakeVersion = $GpiVersion
    boyerVersion = $BoyerVersion
    normalProductCount = $normalProfiles.Length
    normalPassProfileCount = $passProfiles.Length
    normalReviewProfileCount = $reviewProfiles.Length
    profiles = @($profiles)
    architectureDecision = [ordered]@{
        boyerCustomerItemSalesRole = 'WORKFLOW EVIDENCE / CURRENT ROLLING CACHE ONLY - NOT INDEPENDENT PRICE AUTHORITY'
        pricingKey = 'customer + item + quantity + UOM + location + recency/evidence'
        pastaPolicy = 'REVIEW until repeated 62.062 M vs 56.42 M business distinction is resolved'
        exceptionPolicy = 'Mixed/partial/exception rows never inherit normal quantity or price automatically'
        writePolicy = 'NO SALES ORDER WRITE UNTIL NORMAL PROFILES ARE REVIEWED AND AL RESOLVER RULES ARE IMPLEMENTED'
    }
    safety = [ordered]@{
        bcOperations = 'GET ONLY'
        extensionMutation = 'NONE'
        businessDataWrites = 'NONE'
        salesOrderAction = 'NOT CALLED'
        releaseShipInvoicePost = 'NOT CALLED / BLOCKED'
        production = 'HARD BLOCKED'
    }
}

$result | ConvertTo-Json -Depth 30
Write-Host ''
Write-Host 'GPI ORDER INTAKE GIOVANNI RESOLVER PROFILE: GET-ONLY PASS' -ForegroundColor Green
