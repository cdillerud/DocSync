#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$CompanyId         = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'

$ExpectedAppId      = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$ExpectedAppName    = 'GPI Order Intake'
$ExpectedPublisher  = 'Gamer Packaging Inc'
$ExpectedAppVersion = '0.1.0.9'

$Targets = @(
    [pscustomobject][ordered]@{
        Label='BERNER'; CustomerNumber='BERNER'; SourceReference='811476'; ExpectedItem='21759-858231';
        SourceShipToName='Berner Foods'; SourceShipToAddress='5778 Baxter Road'; SourceShipToCity='Rockford'; SourceShipToPostal='61109'
    },
    [pscustomobject][ordered]@{
        Label='HERDEZ'; CustomerNumber='HERDEZ'; SourceReference='000000000004003467'; ExpectedItem='20113526';
        SourceShipToName='SLP INDUSTRIES PLANT'; SourceShipToAddress='AV. INDUSTRIAS 3815'; SourceShipToCity='SLP'; SourceShipToPostal='78395'
    }
)

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
    if (-not (Get-Module -ListAvailable -Name Az.Accounts)) { throw 'Az.Accounts is required.' }
    Import-Module Az.Accounts -ErrorAction Stop
    try {
        $result = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
        $token = Convert-TokenToString $result.Token
        if (-not [string]::IsNullOrWhiteSpace($token)) { return $token }
    }
    catch {}

    Write-Host 'Starting Business Central scoped Microsoft sign-in...' -ForegroundColor Yellow
    Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null
    Connect-AzAccount -Tenant $TenantId -AuthScope 'https://api.businesscentral.dynamics.com' -Scope Process -ErrorAction Stop | Out-Null
    $result = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
    $token = Convert-TokenToString $result.Token
    if ([string]::IsNullOrWhiteSpace($token)) { throw 'Could not acquire Business Central access token.' }
    return $token
}

function Assert-BcUri {
    param([Parameter(Mandatory)][string]$Uri)
    $parsed = [Uri]$Uri
    if ($parsed.Scheme -ne 'https' -or $parsed.Host -ne 'api.businesscentral.dynamics.com') {
        throw ('Unexpected Business Central URI blocked: {0}' -f $Uri)
    }
    if ($Uri.IndexOf($ForbiddenEnv,[StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw ('Forbidden legacy sandbox URI blocked: {0}' -f $Uri)
    }
    if ($Uri.IndexOf('/Production/',[StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw ('Production-like URI blocked: {0}' -f $Uri)
    }
}

function Invoke-BcGet {
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers)
    Assert-BcUri $Uri
    Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 120
}

function Invoke-BcGetAll {
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers,[int]$MaxPages=200)
    $rows = [System.Collections.Generic.List[object]]::new()
    $next = $Uri
    $page = 0
    while (-not [string]::IsNullOrWhiteSpace($next)) {
        $page++
        if ($page -gt $MaxPages) { throw ('Pagination safety bound exceeded ({0} pages): {1}' -f $MaxPages,$Uri) }
        $response = Invoke-BcGet -Uri $next -Headers $Headers
        foreach ($row in @($response.value)) { $rows.Add($row) }
        $nextProp = $response.PSObject.Properties['@odata.nextLink']
        if ($null -eq $nextProp) { $next = $null } else { $next = [string]$nextProp.Value }
    }
    return @($rows)
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    return $Value.Replace("'","''")
}

function Normalize-Reference {
    param([AllowNull()][string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $trimmed = $Value.Trim()
    if ($trimmed -match '^\d+$') {
        $withoutZeros = $trimmed.TrimStart('0')
        if ([string]::IsNullOrEmpty($withoutZeros)) { return '0' }
        return $withoutZeros
    }
    return [regex]::Replace($trimmed.ToUpperInvariant(),'[^A-Z0-9]','')
}

function Test-TextContains {
    param([AllowNull()][string]$Text,[AllowNull()][string]$Needle)
    if ([string]::IsNullOrWhiteSpace($Text) -or [string]::IsNullOrWhiteSpace($Needle)) { return $false }
    return $Text.IndexOf($Needle,[StringComparison]::OrdinalIgnoreCase) -ge 0
}

if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

$environments = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $headers
$envMatches = @($environments.value | Where-Object { [string]$_.name -eq $Environment })
if ($envMatches.Count -ne 1) { throw ('Expected exactly one {0} environment; found {1}.' -f $Environment,$envMatches.Count) }
$environmentType = [string]$envMatches[0].type
if ($environmentType -ine 'sandbox') { throw ('SAFETY STOP: environment type is {0}.' -f $environmentType) }

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet -Uri "$standardRoot/companies" -Headers $headers
$companyMatches = @($companies.value | Where-Object {
    [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatches.Count -ne 1) { throw ('Exact Gamer Packaging company verification failed; found {0}.' -f $companyMatches.Count) }

$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"

$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$installed = @($extensions.value | Where-Object {
    $_.isInstalled -eq $true -and [string]$_.id -eq $ExpectedAppId -and
    [string]$_.displayName -eq $ExpectedAppName -and [string]$_.publisher -eq $ExpectedPublisher -and
    ('{0}.{1}.{2}.{3}' -f $_.versionMajor,$_.versionMinor,$_.versionBuild,$_.versionRevision) -eq $ExpectedAppVersion
})
if ($installed.Count -ne 1) { throw ('Expected exactly one installed {0} {1}; found {2}.' -f $ExpectedAppName,$ExpectedAppVersion,$installed.Count) }

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE 0.1.0.9 - IDENTITY DIAGNOSTICS REV3 / CUSTOMER-SCOPED GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host ('Environment          : {0}' -f $Environment)
Write-Host ('Environment type     : {0}' -f $environmentType)
Write-Host ('Company              : {0}' -f $CompanyName)
Write-Host ('Installed app        : {0} {1}' -f $ExpectedAppName,$ExpectedAppVersion)
Write-Host 'Item Reference query : customer-scoped + expected-item reverse probe; no $top total-result cap'
Write-Host 'Ship-to query        : exact customer-scoped; no $top total-result cap'
Write-Host 'Extension mutation   : NONE' -ForegroundColor Green
Write-Host 'Business-data reads  : GET ONLY' -ForegroundColor Green
Write-Host 'Business-data writes : NONE' -ForegroundColor Green
Write-Host 'Sales-order action   : NOT CALLED / NOT PRESENT' -ForegroundColor Green
Write-Host 'Production           : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

$itemSummaries = @()
$shipSummaries = @()

Write-Host ''
Write-Host 'CUSTOMER_SCOPED_ITEM_REFERENCE_DISCOVERY' -ForegroundColor Cyan
foreach ($target in $Targets) {
    $customerLiteral = Escape-ODataLiteral $target.CustomerNumber
    $customerFilter = [Uri]::EscapeDataString("referenceTypeNumber eq '$customerLiteral'")
    $customerRows = @(Invoke-BcGetAll "$customRoot/orderIntakeItemReferences?`$filter=$customerFilter" $headers)

    $itemLiteral = Escape-ODataLiteral $target.ExpectedItem
    $itemFilter = [Uri]::EscapeDataString("itemNumber eq '$itemLiteral'")
    $itemRows = @(Invoke-BcGetAll "$customRoot/orderIntakeItemReferences?`$filter=$itemFilter" $headers)

    $sourceNorm = Normalize-Reference $target.SourceReference
    $customerSourceMatches = @($customerRows | Where-Object { (Normalize-Reference ([string]$_.referenceNumber)) -eq $sourceNorm })
    $expectedItemRows = @($customerRows | Where-Object { [string]$_.itemNumber -eq [string]$target.ExpectedItem })
    $reverseCustomerRows = @($itemRows | Where-Object { [string]$_.referenceTypeNumber -eq [string]$target.CustomerNumber })

    Write-Host ('ITEM_REF_SCOPE|label={0}|customer={1}|customerRows={2}|expectedItem={3}|expectedItemAllRefs={4}|sourceRef={5}|sourceMatches={6}|expectedItemForCustomer={7}|reverseCustomerRows={8}' -f $target.Label,$target.CustomerNumber,$customerRows.Count,$target.ExpectedItem,$itemRows.Count,$target.SourceReference,$customerSourceMatches.Count,$expectedItemRows.Count,$reverseCustomerRows.Count)

    foreach ($row in $customerRows) {
        Write-Host ('ITEM_REF_CUSTOMER_ROW|label={0}|item={1}|type={2}|typeNo={3}|ref={4}|uom={5}|start={6}|end={7}|description={8}' -f $target.Label,$row.itemNumber,$row.referenceType,$row.referenceTypeNumber,$row.referenceNumber,$row.unitOfMeasureCode,$row.startingDate,$row.endingDate,$row.description)
    }
    if ($customerRows.Count -eq 0) { Write-Host ('ITEM_REF_CUSTOMER_ROW|label={0}|NONE' -f $target.Label) }

    foreach ($row in $itemRows) {
        Write-Host ('ITEM_REF_ITEM_ROW|label={0}|item={1}|type={2}|typeNo={3}|ref={4}|uom={5}|start={6}|end={7}|description={8}' -f $target.Label,$row.itemNumber,$row.referenceType,$row.referenceTypeNumber,$row.referenceNumber,$row.unitOfMeasureCode,$row.startingDate,$row.endingDate,$row.description)
    }
    if ($itemRows.Count -eq 0) { Write-Host ('ITEM_REF_ITEM_ROW|label={0}|item={1}|NONE' -f $target.Label,$target.ExpectedItem) }

    $itemSummaries += [pscustomobject][ordered]@{
        label = $target.Label
        customerNumber = $target.CustomerNumber
        sourceReference = $target.SourceReference
        expectedItem = $target.ExpectedItem
        customerScopedRows = $customerRows.Count
        sourceReferenceMatches = $customerSourceMatches.Count
        expectedItemRowsForCustomer = $expectedItemRows.Count
        expectedItemAllReferenceRows = $itemRows.Count
        expectedItemReverseCustomerRows = $reverseCustomerRows.Count
    }
}

Write-Host ''
Write-Host 'CUSTOMER_SCOPED_SHIP_TO_DISCOVERY' -ForegroundColor Cyan
foreach ($target in $Targets) {
    $customerLiteral = Escape-ODataLiteral $target.CustomerNumber
    $filter = [Uri]::EscapeDataString("customerNumber eq '$customerLiteral'")
    $rows = @(Invoke-BcGetAll "$customRoot/orderIntakeShipToAddresses?`$filter=$filter" $headers)

    $strong = @($rows | Where-Object {
        (Test-TextContains ([string]$_.name) $target.SourceShipToName) -or
        (Test-TextContains ([string]$_.addressLine1) $target.SourceShipToAddress) -or
        ((Test-TextContains ([string]$_.city) $target.SourceShipToCity) -and (Test-TextContains ([string]$_.postalCode) $target.SourceShipToPostal))
    })

    Write-Host ('SHIP_TO_SCOPE|label={0}|customer={1}|rows={2}|strongSourceCandidates={3}|sourceName={4}|sourceAddress={5}|sourceCity={6}|sourcePostal={7}' -f $target.Label,$target.CustomerNumber,$rows.Count,$strong.Count,$target.SourceShipToName,$target.SourceShipToAddress,$target.SourceShipToCity,$target.SourceShipToPostal)
    foreach ($row in $rows) {
        Write-Host ('SHIP_TO_ROW|label={0}|customer={1}|code={2}|name={3}|name2={4}|address1={5}|address2={6}|city={7}|state={8}|postal={9}|country={10}|location={11}|shipmentMethod={12}' -f $target.Label,$row.customerNumber,$row.code,$row.name,$row.name2,$row.addressLine1,$row.addressLine2,$row.city,$row.state,$row.postalCode,$row.countryCode,$row.locationCode,$row.shipmentMethodCode)
    }
    if ($rows.Count -eq 0) { Write-Host ('SHIP_TO_ROW|label={0}|customer={1}|NONE' -f $target.Label,$target.CustomerNumber) }

    $shipSummaries += [pscustomobject][ordered]@{
        label = $target.Label
        customerNumber = $target.CustomerNumber
        shipToRows = $rows.Count
        strongSourceCandidates = $strong.Count
    }
}

Write-Host ''
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE 0.1.0.9 IDENTITY DIAGNOSTICS REV3 RESULT' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'Installed app          : PASS / exact PRE 0.1.0.9'
Write-Host 'Item Reference reads   : CUSTOMER-SCOPED + REVERSE ITEM / GET ONLY'
Write-Host 'Ship-to Address reads  : CUSTOMER-SCOPED / GET ONLY'
Write-Host 'Extension mutation     : NONE'
Write-Host 'Business-data writes   : NONE'
Write-Host 'Sales-order action     : NOT CALLED'
Write-Host 'Write authorization    : NOT GRANTED'
Write-Host 'Production             : HARD BLOCKED'
Write-Host ('=' * 120) -ForegroundColor Cyan

[ordered]@{
    success = $true
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    installedApp = "$ExpectedAppName $ExpectedAppVersion"
    itemReferenceSummary = $itemSummaries
    shipToSummary = $shipSummaries
    writeAuthorization = 'NOT_GRANTED'
    safety = [ordered]@{
        extensionMutation = 'NONE'
        businessDataReads = 'GET_ONLY'
        businessDataWrites = 'NONE'
        salesOrderAction = 'NOT_CALLED'
        releaseShipInvoicePost = 'NOT_CALLED_BLOCKED'
        production = 'HARD_BLOCKED'
    }
} | ConvertTo-Json -Depth 10