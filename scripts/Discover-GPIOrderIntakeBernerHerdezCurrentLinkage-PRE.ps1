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
$ExpectedAppId     = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$ExpectedAppName   = 'GPI Order Intake'
$ExpectedPublisher = 'Gamer Packaging Inc'
$ExpectedVersion   = '0.1.0.10'

$BernerCustomer        = 'BERNER'
$BernerSourcePart      = '811476'
$BernerSourceAlias     = '21579-858231'
$BernerBcItem          = '21759-858231'
$BernerShipTo          = '78899028'
$BernerChains = @(
    [pscustomobject]@{ CustomerPo='241355'; SalesOrder='114600' },
    [pscustomobject]@{ CustomerPo='241356'; SalesOrder='114601' },
    [pscustomobject]@{ CustomerPo='241357'; SalesOrder='114602' }
)

$HerdezCustomer        = 'HERDEZ'
$HerdezSourcePo        = '4500063632'
$HerdezSourcePart      = '000000000004003467'
$HerdezBcItem          = '20113526'
$HerdezShipTo          = '001'
$HerdezLinkedPurchase  = '117357'

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
    if ($u.Scheme -ne 'https' -or $u.Host -ne 'api.businesscentral.dynamics.com') {
        throw "Unexpected Business Central URI blocked: $Uri"
    }
    if ($Uri.IndexOf($ForbiddenEnv,[StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Forbidden legacy sandbox URI blocked: $Uri"
    }
    if ($Uri.IndexOf('/Production/',[StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Production-like URI blocked: $Uri"
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
        if ($page -gt $MaxPages) { throw "Pagination safety bound exceeded ($MaxPages pages): $Uri" }
        $r = Invoke-BcGet -Uri $next -Headers $Headers
        foreach ($row in @($r.value)) { $rows.Add($row) }
        $nextProp = $r.PSObject.Properties['@odata.nextLink']
        if ($null -eq $nextProp) { $next = $null } else { $next = [string]$nextProp.Value }
    }
    return @($rows)
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    return $Value.Replace("'", "''")
}

function New-FilterUri {
    param(
        [Parameter(Mandatory)][string]$Root,
        [Parameter(Mandatory)][string]$EntitySet,
        [Parameter(Mandatory)][string]$Filter
    )
    $encoded = [Uri]::EscapeDataString($Filter)
    return "${Root}/${EntitySet}?`$filter=$encoded"
}

function Normalize-Key {
    param([AllowNull()][string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    return [regex]::Replace($Value.ToUpperInvariant(),'[^A-Z0-9]','')
}

function Get-VersionString {
    param([Parameter(Mandatory)]$Extension)
    return ('{0}.{1}.{2}.{3}' -f $Extension.versionMajor,$Extension.versionMinor,$Extension.versionBuild,$Extension.versionRevision)
}

if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

$envs = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $headers
$envMatch = @($envs.value | Where-Object { [string]$_.name -eq $Environment })
if ($envMatch.Count -ne 1) { throw "Expected exactly one $Environment; found $($envMatch.Count)." }
$environmentType = [string]$envMatch[0].type
if ($environmentType -ine 'sandbox') { throw "SAFETY STOP: $Environment is type '$environmentType', not sandbox." }

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet -Uri "$standardRoot/companies" -Headers $headers
$companyMatch = @($companies.value | Where-Object {
    [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatch.Count -ne 1) { throw "Exact Gamer Packaging company verification failed; found $($companyMatch.Count)." }

$companyRoot = "$standardRoot/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"
$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"

$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$app = @($extensions.value | Where-Object {
    $_.isInstalled -eq $true -and
    [string]$_.id -eq $ExpectedAppId -and
    [string]$_.displayName -eq $ExpectedAppName -and
    [string]$_.publisher -eq $ExpectedPublisher -and
    (Get-VersionString $_) -eq $ExpectedVersion
})
if ($app.Count -ne 1) { throw "Expected installed $ExpectedAppName $ExpectedVersion; found $($app.Count)." }

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - BERNER ALIAS + HERDEZ CURRENT LINKAGE / PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment          : $Environment"
Write-Host "Environment type     : $environmentType"
Write-Host "Company              : $CompanyName"
Write-Host "Installed app        : $ExpectedAppName $ExpectedVersion"
Write-Host 'Berner evidence      : 3 customer POs / 3 historical Sales Orders'
Write-Host 'Herdez evidence      : customer PO + linked Gamer Purchase Order + current Sales Order search'
Write-Host 'HTTP methods         : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation   : NONE' -ForegroundColor Green
Write-Host 'Business-data writes : NONE' -ForegroundColor Green
Write-Host 'Sales-order action   : NOT CALLED / NOT PRESENT' -ForegroundColor Green
Write-Host 'Production           : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

Write-Host ''
Write-Host 'BERNER_ITEM_MASTER_ALIAS_PROBE' -ForegroundColor Cyan
$itemSelect = [Uri]::EscapeDataString('id,number,displayName,type,blocked,baseUnitOfMeasureCode')
foreach ($itemNumber in @($BernerSourceAlias,$BernerBcItem)) {
    $lit = Escape-ODataLiteral $itemNumber
    $filter = [Uri]::EscapeDataString("number eq '$lit'")
    $rows = @(Invoke-BcGetAll "$companyRoot/items?`$select=$itemSelect&`$filter=$filter" $headers)
    if ($rows.Count -eq 0) {
        Write-Host "BERNER_ITEM_PROBE|item=$itemNumber|matches=0"
    }
    foreach ($row in $rows) {
        Write-Host ('BERNER_ITEM_PROBE|item={0}|matches={1}|name={2}|type={3}|blocked={4}|baseUom={5}' -f $row.number,$rows.Count,$row.displayName,$row.type,$row.blocked,$row.baseUnitOfMeasureCode)
    }
}

Write-Host ''
Write-Host 'BERNER_REPEATED_TRANSACTION_LINKAGE' -ForegroundColor Cyan
$bernerSummaries = [System.Collections.Generic.List[object]]::new()
foreach ($chain in $BernerChains) {
    $so = Escape-ODataLiteral ([string]$chain.SalesOrder)
    $po = [string]$chain.CustomerPo
    $headerFilter = "documentNumber eq '$so' and sellToCustomerNumber eq '$BernerCustomer'"
    $lineFilter = "documentNumber eq '$so' and sellToCustomerNumber eq '$BernerCustomer'"
    $headersArc = @(Invoke-BcGetAll (New-FilterUri $customRoot 'orderIntakeSalesHeaderArchives' $headerFilter) $headers)
    $linesArc = @(Invoke-BcGetAll (New-FilterUri $customRoot 'orderIntakeSalesLineArchives' $lineFilter) $headers)
    $headerPoMatches = @($headersArc | Where-Object { [string]$_.externalDocumentNumber -eq $po })
    $itemLines = @($linesArc | Where-Object { [string]$_.itemNumber -eq $BernerBcItem })

    foreach ($h in $headersArc) {
        Write-Host ('BERNER_HEADER|po={0}|so={1}|external={2}|customer={3}|shipTo={4}|location={5}|orderDate={6}|shipmentDate={7}|version={8}' -f $po,$h.documentNumber,$h.externalDocumentNumber,$h.sellToCustomerNumber,$h.shipToCode,$h.locationCode,$h.orderDate,$h.shipmentDate,$h.versionNumber)
    }
    foreach ($l in $itemLines) {
        Write-Host ('BERNER_LINE|po={0}|so={1}|item={2}|qty={3}|uom={4}|price={5}|location={6}|itemRef={7}|version={8}' -f $po,$l.documentNumber,$l.itemNumber,$l.quantity,$l.unitOfMeasureCode,$l.unitPrice,$l.locationCode,$l.itemReferenceNumber,$l.versionNumber)
    }

    $bernerSummaries.Add([pscustomobject]@{
        customerPo = $po
        salesOrder = [string]$chain.SalesOrder
        headerRows = $headersArc.Count
        exactPoHeaderMatches = $headerPoMatches.Count
        expectedItemLines = $itemLines.Count
        exactShipToHeaderMatches = @($headersArc | Where-Object { [string]$_.shipToCode -eq $BernerShipTo }).Count
    })
}

$bernerExactChains = @($bernerSummaries | Where-Object {
    $_.exactPoHeaderMatches -gt 0 -and $_.expectedItemLines -gt 0 -and $_.exactShipToHeaderMatches -gt 0
}).Count
Write-Host ('BERNER_CHAIN_SUMMARY|sourcePart={0}|sourceAlias={1}|bcItem={2}|shipTo={3}|chains={4}|exactChains={5}' -f $BernerSourcePart,$BernerSourceAlias,$BernerBcItem,$BernerShipTo,$bernerSummaries.Count,$bernerExactChains)

Write-Host ''
Write-Host 'HERDEZ_CURRENT_SALES_ORDER_LINKAGE' -ForegroundColor Cyan
$hc = Escape-ODataLiteral $HerdezCustomer
$hp = Escape-ODataLiteral $HerdezSourcePo
$exactOrderFilter = "customerNumber eq '$hc' and externalDocumentNumber eq '$hp'"
$exactOrders = @(Invoke-BcGetAll (New-FilterUri $customRoot 'orderIntakeOrders' $exactOrderFilter) $headers)

$customerOrderFilter = "customerNumber eq '$hc'"
$allHerdezOrders = @(Invoke-BcGetAll (New-FilterUri $customRoot 'orderIntakeOrders' $customerOrderFilter) $headers)
$sourcePoNorm = Normalize-Key $HerdezSourcePo
$normalizedPoOrders = @($allHerdezOrders | Where-Object {
    (Normalize-Key ([string]$_.externalDocumentNumber)).Contains($sourcePoNorm)
})

Write-Host ('HERDEZ_CURRENT_ORDER_SCOPE|customer={0}|sourcePo={1}|exactExternalMatches={2}|customerOpenOrders={3}|normalizedPoCandidates={4}|linkedPurchaseOrder={5}' -f $HerdezCustomer,$HerdezSourcePo,$exactOrders.Count,$allHerdezOrders.Count,$normalizedPoOrders.Count,$HerdezLinkedPurchase)
foreach ($o in $normalizedPoOrders) {
    Write-Host ('HERDEZ_CURRENT_ORDER|number={0}|customer={1}|external={2}|orderDate={3}|shipmentDate={4}|location={5}|status={6}' -f $o.number,$o.customerNumber,$o.externalDocumentNumber,$o.orderDate,$o.shipmentDate,$o.locationCode,$o.status)
}
if ($normalizedPoOrders.Count -eq 0) { Write-Host 'HERDEZ_CURRENT_ORDER|NONE_FOR_SOURCE_PO' }

$currentLineFilter = "sellToCustomerNumber eq '$hc' and itemNumber eq '$HerdezBcItem'"
$currentItemLines = @(Invoke-BcGetAll (New-FilterUri $customRoot 'orderIntakeLines' $currentLineFilter) $headers)
Write-Host ('HERDEZ_CURRENT_ITEM_LINE_SCOPE|customer={0}|item={1}|rows={2}' -f $HerdezCustomer,$HerdezBcItem,$currentItemLines.Count)
foreach ($l in $currentItemLines) {
    Write-Host ('HERDEZ_CURRENT_LINE|order={0}|item={1}|qty={2}|uom={3}|price={4}|location={5}|shipmentDate={6}|description={7}' -f $l.documentNumber,$l.itemNumber,$l.quantity,$l.unitOfMeasureCode,$l.unitPrice,$l.locationCode,$l.shipmentDate,$l.description)
}
if ($currentItemLines.Count -eq 0) { Write-Host 'HERDEZ_CURRENT_LINE|NONE' }

$currentLineOrderNos = @($currentItemLines | ForEach-Object { [string]$_.documentNumber } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique)
foreach ($orderNo in $currentLineOrderNos) {
    $ol = Escape-ODataLiteral $orderNo
    $f = "number eq '$ol'"
    $rows = @(Invoke-BcGetAll (New-FilterUri $customRoot 'orderIntakeOrders' $f) $headers)
    foreach ($o in $rows) {
        Write-Host ('HERDEZ_ITEM_ORDER_HEADER|number={0}|external={1}|customer={2}|orderDate={3}|shipmentDate={4}|location={5}|status={6}' -f $o.number,$o.externalDocumentNumber,$o.customerNumber,$o.orderDate,$o.shipmentDate,$o.locationCode,$o.status)
    }
}

Write-Host ''
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE BERNER/HERDEZ CURRENT LINKAGE RESULT' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Berner source part      : $BernerSourcePart"
Write-Host "Berner source alias     : $BernerSourceAlias"
Write-Host "Berner BC item          : $BernerBcItem"
Write-Host "Berner exact chains     : $bernerExactChains / $($bernerSummaries.Count)"
Write-Host "Herdez source PO        : $HerdezSourcePo"
Write-Host "Herdez source part      : $HerdezSourcePart"
Write-Host "Herdez BC item          : $HerdezBcItem"
Write-Host "Herdez current PO match : $($normalizedPoOrders.Count)"
Write-Host "Herdez current item rows: $($currentItemLines.Count)"
Write-Host 'Extension mutation      : NONE' -ForegroundColor Green
Write-Host 'Business-data writes    : NONE' -ForegroundColor Green
Write-Host 'Sales-order action      : NOT CALLED' -ForegroundColor Green
Write-Host 'Write authorization     : NOT GRANTED' -ForegroundColor Green
Write-Host 'Production              : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

[pscustomobject][ordered]@{
    success = $true
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    installedApp = "$ExpectedAppName $ExpectedVersion"
    berner = [ordered]@{
        sourcePart = $BernerSourcePart
        sourceAlias = $BernerSourceAlias
        bcItem = $BernerBcItem
        shipTo = $BernerShipTo
        exactChains = $bernerExactChains
        totalChains = $bernerSummaries.Count
        chains = @($bernerSummaries)
    }
    herdez = [ordered]@{
        sourcePo = $HerdezSourcePo
        sourcePart = $HerdezSourcePart
        bcItem = $HerdezBcItem
        expectedShipTo = $HerdezShipTo
        linkedPurchaseOrder = $HerdezLinkedPurchase
        exactExternalOrderMatches = $exactOrders.Count
        normalizedPoCandidates = $normalizedPoOrders.Count
        currentItemLineRows = $currentItemLines.Count
    }
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