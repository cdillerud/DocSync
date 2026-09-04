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

$BernerCustomer = 'BERNER'
$BernerItem     = '21759-858231'
$BernerUom      = 'M'
$BernerLocation = '00'
$BernerShipTo   = '78899028'
$BernerSourcePrice = [decimal]243.43
$BernerChains = @(
    [pscustomobject]@{ CustomerPo='241355'; SalesOrder='114600'; SourceOrderDate='2026-05-14'; SourceDeliveryDate='2026-07-20' },
    [pscustomobject]@{ CustomerPo='241356'; SalesOrder='114601'; SourceOrderDate='2026-05-14'; SourceDeliveryDate='2026-07-20' },
    [pscustomobject]@{ CustomerPo='241357'; SalesOrder='114602'; SourceOrderDate='2026-05-14'; SourceDeliveryDate='2026-07-20' }
)

$HerdezCustomer = 'HERDEZ'
$HerdezItem     = '20113526'
$HerdezUom      = 'M'
$HerdezLocation = '00'
$HerdezShipTo   = '001'
$HerdezSourcePrice = [decimal]225.75
$HerdezChains = @(
    [pscustomobject]@{ CustomerPo='4500063632'; SalesOrder='117357'; SourceOrderDate='2026-07-30'; SourceDeliveryDate='2026-09-01' },
    [pscustomobject]@{ CustomerPo='4500063739'; SalesOrder='117358'; SourceOrderDate='2026-07-30'; SourceDeliveryDate='2026-09-01' },
    [pscustomobject]@{ CustomerPo='4500063770'; SalesOrder='117371'; SourceOrderDate='2026-07-30'; SourceDeliveryDate='2026-10-01' }
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
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers,[int]$MaxPages=300)
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

function Get-VersionString {
    param([Parameter(Mandatory)]$Extension)
    return ('{0}.{1}.{2}.{3}' -f $Extension.versionMajor,$Extension.versionMinor,$Extension.versionBuild,$Extension.versionRevision)
}

function Get-PropString {
    param([Parameter(Mandatory)]$Object,[Parameter(Mandatory)][string]$Name)
    $p = $Object.PSObject.Properties[$Name]
    if ($null -eq $p -or $null -eq $p.Value) { return '' }
    return [string]$p.Value
}

function Get-IsoDate {
    param([AllowNull()]$Value)
    if ($null -eq $Value) { return '' }
    $s = [string]$Value
    if ([string]::IsNullOrWhiteSpace($s) -or $s.StartsWith('0001-01-01')) { return '' }
    if ($s.Length -ge 10) { return $s.Substring(0,10) }
    return $s
}

function Date-DaysBetween {
    param([Parameter(Mandatory)][string]$Earlier,[Parameter(Mandatory)][string]$Later)
    $a = [DateTime]::ParseExact($Earlier,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture)
    $b = [DateTime]::ParseExact($Later,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture)
    return [int]($b - $a).TotalDays
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
Write-Host 'GPI ORDER INTAKE - CUSTOMER PDF PRICE + DATE AUTHORITY DISCOVERY / PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment          : $Environment"
Write-Host "Environment type     : $environmentType"
Write-Host "Company              : $CompanyName"
Write-Host "Installed app        : $ExpectedAppName $ExpectedVersion"
Write-Host 'Pricing policy test  : repeated BC transaction evidence is authority; source price corroborates only'
Write-Host 'Date policy test     : source PO date remains evidence; customer delivery/receive date mapped only where repeated BC behavior proves semantics'
Write-Host 'HTTP methods         : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation   : NONE' -ForegroundColor Green
Write-Host 'Business-data writes : NONE' -ForegroundColor Green
Write-Host 'Sales-order action   : NOT CALLED / NOT PRESENT' -ForegroundColor Green
Write-Host 'Production           : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

# ---------------------------------------------------------------------------------------------------------------------
# Berner pricing authority: posted invoice lines joined to posted invoice headers for exact Ship-to.
# ---------------------------------------------------------------------------------------------------------------------
Write-Host ''
Write-Host 'BERNER_PRICE_AUTHORITY' -ForegroundColor Cyan
$bc = Escape-ODataLiteral $BernerCustomer
$bi = Escape-ODataLiteral $BernerItem
$bs = Escape-ODataLiteral $BernerShipTo
$bernerHeaderFilter = "sellToCustomerNumber eq '$bc' and shipToCode eq '$bs'"
$bernerPostedHeaders = @(Invoke-BcGetAll (New-FilterUri $customRoot 'orderIntakeSalesInvoiceHeaderHistories' $bernerHeaderFilter) $headers)
$bernerInvoiceSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($h in $bernerPostedHeaders) { [void]$bernerInvoiceSet.Add([string]$h.documentNumber) }

$bernerLineFilter = "sellToCustomerNumber eq '$bc' and itemNumber eq '$bi' and unitOfMeasureCode eq '$BernerUom' and locationCode eq '$BernerLocation'"
$bernerPostedLinesAll = @(Invoke-BcGetAll (New-FilterUri $customRoot 'orderIntakeSalesInvoiceLineHistories' $bernerLineFilter) $headers)
$bernerPriceRows = @($bernerPostedLinesAll | Where-Object { $bernerInvoiceSet.Contains([string]$_.documentNumber) } | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
$bernerLatestTwo = @($bernerPriceRows | Select-Object -First 2)
$bernerLatestTwoAgree = $bernerLatestTwo.Count -eq 2 -and [decimal]$bernerLatestTwo[0].unitPrice -gt 0 -and [decimal]$bernerLatestTwo[0].unitPrice -eq [decimal]$bernerLatestTwo[1].unitPrice
$bernerResolvedPrice = if ($bernerLatestTwoAgree) { [decimal]$bernerLatestTwo[0].unitPrice } else { [decimal]0 }
$bernerSourceCorroborates = $bernerLatestTwoAgree -and $bernerResolvedPrice -eq $BernerSourcePrice
$bernerMatchingPriceCount = if ($bernerLatestTwoAgree) { @($bernerPriceRows | Where-Object { [decimal]$_.unitPrice -eq $bernerResolvedPrice }).Count } else { 0 }
Write-Host ('BERNER_PRICE_SCOPE|customer={0}|item={1}|uom={2}|location={3}|shipTo={4}|shipToHeaders={5}|priceRows={6}|latestTwoAgree={7}|resolvedPrice={8}|matchingResolvedRows={9}|sourcePrice={10}|sourceCorroborates={11}' -f $BernerCustomer,$BernerItem,$BernerUom,$BernerLocation,$BernerShipTo,$bernerPostedHeaders.Count,$bernerPriceRows.Count,$bernerLatestTwoAgree,$bernerResolvedPrice,$bernerMatchingPriceCount,$BernerSourcePrice,$bernerSourceCorroborates)
foreach ($row in @($bernerPriceRows | Select-Object -First 5)) {
    Write-Host ('BERNER_PRICE_ROW|invoice={0}|created={1}|shipDate={2}|qty={3}|uom={4}|price={5}|location={6}' -f $row.documentNumber,$row.systemCreatedAt,$row.shipmentDate,$row.quantity,$row.unitOfMeasureCode,$row.unitPrice,$row.locationCode)
}

# ---------------------------------------------------------------------------------------------------------------------
# Berner date semantics: three source PO dates/receive dates vs archived BC order/shipment/requested-delivery fields.
# ---------------------------------------------------------------------------------------------------------------------
Write-Host ''
Write-Host 'BERNER_DATE_AUTHORITY' -ForegroundColor Cyan
$bernerDateRows = [System.Collections.Generic.List[object]]::new()
foreach ($chain in $BernerChains) {
    $soLit = Escape-ODataLiteral ([string]$chain.SalesOrder)
    $filter = "documentNumber eq '$soLit' and sellToCustomerNumber eq '$bc'"
    $rows = @(Invoke-BcGetAll (New-FilterUri $customRoot 'orderIntakeSalesHeaderArchives' $filter) $headers)
    $exact = @($rows | Where-Object { [string]$_.externalDocumentNumber -eq [string]$chain.CustomerPo } | Sort-Object {[int]$_.versionNumber} -Descending | Select-Object -First 1)
    if ($exact.Count -ne 1) {
        Write-Host "BERNER_DATE_ROW|po=$($chain.CustomerPo)|so=$($chain.SalesOrder)|BC_ARCHIVE_NOT_EXACT"
        continue
    }
    $h = $exact[0]
    $bcOrder = Get-IsoDate $h.orderDate
    $bcShipment = Get-IsoDate $h.shipmentDate
    $bcRequested = Get-IsoDate $h.requestedDeliveryDate
    $sourceOrderMatchesBcOrder = $bcOrder -eq [string]$chain.SourceOrderDate
    $sourceDeliveryMatchesShipment = $bcShipment -eq [string]$chain.SourceDeliveryDate
    $sourceDeliveryMatchesRequested = $bcRequested -eq [string]$chain.SourceDeliveryDate
    Write-Host ('BERNER_DATE_ROW|po={0}|so={1}|sourceOrderDate={2}|bcOrderDate={3}|sourceOrderEqualsBcOrder={4}|sourceReceiveDate={5}|bcRequestedDelivery={6}|bcShipmentDate={7}|sourceReceiveEqualsRequested={8}|sourceReceiveEqualsShipment={9}|shipTo={10}' -f $chain.CustomerPo,$chain.SalesOrder,$chain.SourceOrderDate,$bcOrder,$sourceOrderMatchesBcOrder,$chain.SourceDeliveryDate,$bcRequested,$bcShipment,$sourceDeliveryMatchesRequested,$sourceDeliveryMatchesShipment,$h.shipToCode)
    $bernerDateRows.Add([pscustomobject]@{
        customerPo = [string]$chain.CustomerPo
        sourceOrderEqualsBcOrder = $sourceOrderMatchesBcOrder
        sourceDeliveryEqualsRequested = $sourceDeliveryMatchesRequested
        sourceDeliveryEqualsShipment = $sourceDeliveryMatchesShipment
    })
}
$bernerShipmentDirectMatches = @($bernerDateRows | Where-Object { $_.sourceDeliveryEqualsShipment }).Count
$bernerOrderDateDirectMatches = @($bernerDateRows | Where-Object { $_.sourceOrderEqualsBcOrder }).Count
Write-Host ('BERNER_DATE_SUMMARY|rows={0}|sourceReceiveEqualsBcShipment={1}|sourcePoDateEqualsBcOrderDate={2}|candidatePolicy={3}' -f $bernerDateRows.Count,$bernerShipmentDirectMatches,$bernerOrderDateDirectMatches,($(if ($bernerDateRows.Count -eq 3 -and $bernerShipmentDirectMatches -eq 3) { 'BERNER_RECEIVE_DATE_TO_SHIPMENT_DATE_ONLY' } else { 'REVIEW' })))

# ---------------------------------------------------------------------------------------------------------------------
# Herdez pricing authority: exact source-linked current Sales Orders only.
# ---------------------------------------------------------------------------------------------------------------------
Write-Host ''
Write-Host 'HERDEZ_PRICE_AUTHORITY' -ForegroundColor Cyan
$hc = Escape-ODataLiteral $HerdezCustomer
$hi = Escape-ODataLiteral $HerdezItem
$herdezOrders = @(Invoke-BcGetAll (New-FilterUri $customRoot 'orderIntakeOrders' "customerNumber eq '$hc'") $headers)
$herdezLines = @(Invoke-BcGetAll (New-FilterUri $customRoot 'orderIntakeLines' "sellToCustomerNumber eq '$hc' and itemNumber eq '$hi' and unitOfMeasureCode eq '$HerdezUom' and locationCode eq '$HerdezLocation'") $headers)
$herdezSourcePoSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($chain in $HerdezChains) { [void]$herdezSourcePoSet.Add([string]$chain.CustomerPo) }
$herdezOrderNoSet = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($o in $herdezOrders) {
    if ($herdezSourcePoSet.Contains([string]$o.externalDocumentNumber)) { [void]$herdezOrderNoSet.Add([string]$o.number) }
}
$herdezPriceRows = @($herdezLines | Where-Object { $herdezOrderNoSet.Contains([string]$_.documentNumber) } | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
$herdezLatestTwo = @($herdezPriceRows | Select-Object -First 2)
$herdezLatestTwoAgree = $herdezLatestTwo.Count -eq 2 -and [decimal]$herdezLatestTwo[0].unitPrice -gt 0 -and [decimal]$herdezLatestTwo[0].unitPrice -eq [decimal]$herdezLatestTwo[1].unitPrice
$herdezResolvedPrice = if ($herdezLatestTwoAgree) { [decimal]$herdezLatestTwo[0].unitPrice } else { [decimal]0 }
$herdezSourceCorroborates = $herdezLatestTwoAgree -and $herdezResolvedPrice -eq $HerdezSourcePrice
$herdezMatchingPriceCount = if ($herdezLatestTwoAgree) { @($herdezPriceRows | Where-Object { [decimal]$_.unitPrice -eq $herdezResolvedPrice }).Count } else { 0 }
Write-Host ('HERDEZ_PRICE_SCOPE|customer={0}|item={1}|uom={2}|location={3}|sourceLinkedOrders={4}|priceRows={5}|latestTwoAgree={6}|resolvedPrice={7}|matchingResolvedRows={8}|sourcePrice={9}|sourceCorroborates={10}' -f $HerdezCustomer,$HerdezItem,$HerdezUom,$HerdezLocation,$herdezOrderNoSet.Count,$herdezPriceRows.Count,$herdezLatestTwoAgree,$herdezResolvedPrice,$herdezMatchingPriceCount,$HerdezSourcePrice,$herdezSourceCorroborates)
foreach ($row in $herdezPriceRows) {
    $header = @($herdezOrders | Where-Object { [string]$_.number -eq [string]$row.documentNumber } | Select-Object -First 1)
    $external = if ($header.Count -eq 1) { [string]$header[0].externalDocumentNumber } else { '' }
    Write-Host ('HERDEZ_PRICE_ROW|order={0}|external={1}|created={2}|shipmentDate={3}|qty={4}|uom={5}|price={6}|location={7}' -f $row.documentNumber,$external,$row.systemCreatedAt,$row.shipmentDate,$row.quantity,$row.unitOfMeasureCode,$row.unitPrice,$row.locationCode)
}

# ---------------------------------------------------------------------------------------------------------------------
# Herdez date semantics: compare source delivery dates to standard v2.0 Sales Order requested/shipment dates.
# Full entity GET is intentional so the gate fails informatively if a field is absent instead of assuming schema.
# ---------------------------------------------------------------------------------------------------------------------
Write-Host ''
Write-Host 'HERDEZ_DATE_AUTHORITY' -ForegroundColor Cyan
$herdezDateRows = [System.Collections.Generic.List[object]]::new()
foreach ($chain in $HerdezChains) {
    $so = Escape-ODataLiteral ([string]$chain.SalesOrder)
    $stdRows = @(Invoke-BcGetAll (New-FilterUri $companyRoot 'salesOrders' "number eq '$so'") $headers)
    if ($stdRows.Count -ne 1) {
        Write-Host "HERDEZ_DATE_ROW|po=$($chain.CustomerPo)|so=$($chain.SalesOrder)|STANDARD_ORDER_MATCHES=$($stdRows.Count)"
        continue
    }
    $o = $stdRows[0]
    $external = Get-PropString $o 'externalDocumentNumber'
    $bcOrder = Get-IsoDate (Get-PropString $o 'orderDate')
    $bcRequested = Get-IsoDate (Get-PropString $o 'requestedDeliveryDate')
    $bcPromised = Get-IsoDate (Get-PropString $o 'promisedDeliveryDate')
    $bcShipment = Get-IsoDate (Get-PropString $o 'shipmentDate')
    $requestedFieldPresent = $o.PSObject.Properties.Name -contains 'requestedDeliveryDate'
    $sourceOrderMatchesBcOrder = $bcOrder -eq [string]$chain.SourceOrderDate
    $sourceDeliveryMatchesRequested = $bcRequested -eq [string]$chain.SourceDeliveryDate
    $sourceDeliveryMatchesShipment = $bcShipment -eq [string]$chain.SourceDeliveryDate
    $leadDays = if (-not [string]::IsNullOrWhiteSpace($bcShipment)) { Date-DaysBetween $bcShipment ([string]$chain.SourceDeliveryDate) } else { $null }
    $postalAddress = Get-PropString $o 'shippingPostalAddress'
    Write-Host ('HERDEZ_DATE_ROW|po={0}|so={1}|external={2}|sourceOrderDate={3}|bcOrderDate={4}|sourceOrderEqualsBcOrder={5}|sourceDelivery={6}|requestedFieldPresent={7}|bcRequestedDelivery={8}|bcPromisedDelivery={9}|bcShipmentDate={10}|sourceDeliveryEqualsRequested={11}|sourceDeliveryEqualsShipment={12}|shipmentToDeliveryCalendarDays={13}|shippingPostalAddress={14}' -f $chain.CustomerPo,$chain.SalesOrder,$external,$chain.SourceOrderDate,$bcOrder,$sourceOrderMatchesBcOrder,$chain.SourceDeliveryDate,$requestedFieldPresent,$bcRequested,$bcPromised,$bcShipment,$sourceDeliveryMatchesRequested,$sourceDeliveryMatchesShipment,$leadDays,$postalAddress)
    $herdezDateRows.Add([pscustomobject]@{
        customerPo = [string]$chain.CustomerPo
        requestedFieldPresent = $requestedFieldPresent
        sourceOrderEqualsBcOrder = $sourceOrderMatchesBcOrder
        sourceDeliveryEqualsRequested = $sourceDeliveryMatchesRequested
        sourceDeliveryEqualsShipment = $sourceDeliveryMatchesShipment
        shipmentToDeliveryCalendarDays = $leadDays
    })
}
$herdezRequestedMatches = @($herdezDateRows | Where-Object { $_.sourceDeliveryEqualsRequested }).Count
$herdezShipmentDirectMatches = @($herdezDateRows | Where-Object { $_.sourceDeliveryEqualsShipment }).Count
$herdezOrderDateDirectMatches = @($herdezDateRows | Where-Object { $_.sourceOrderEqualsBcOrder }).Count
$herdezDatePolicy = if ($herdezDateRows.Count -eq 3 -and $herdezRequestedMatches -eq 3) { 'SOURCE_DELIVERY_TO_BC_REQUESTED_DELIVERY; BC_CALCULATES_SHIPMENT' } else { 'REVIEW_REQUIRED' }
Write-Host ('HERDEZ_DATE_SUMMARY|rows={0}|sourceDeliveryEqualsBcRequested={1}|sourceDeliveryEqualsBcShipment={2}|sourcePoDateEqualsBcOrderDate={3}|candidatePolicy={4}' -f $herdezDateRows.Count,$herdezRequestedMatches,$herdezShipmentDirectMatches,$herdezOrderDateDirectMatches,$herdezDatePolicy)

$priceAuthorityReady = $bernerLatestTwoAgree -and $bernerSourceCorroborates -and $herdezLatestTwoAgree -and $herdezSourceCorroborates
$bernerDateReady = $bernerDateRows.Count -eq 3 -and $bernerShipmentDirectMatches -eq 3
$herdezDateReady = $herdezDateRows.Count -eq 3 -and $herdezRequestedMatches -eq 3

Write-Host ''
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE CUSTOMER PDF PRICE + DATE AUTHORITY RESULT' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host ("Berner price authority : {0}" -f $(if ($bernerLatestTwoAgree -and $bernerSourceCorroborates) { 'PASS / repeated posted BC evidence + source corroboration' } else { 'REVIEW' }))
Write-Host ("Herdez price authority : {0}" -f $(if ($herdezLatestTwoAgree -and $herdezSourceCorroborates) { 'PASS / repeated current BC evidence + source corroboration' } else { 'REVIEW' }))
Write-Host ("Berner date semantics  : {0}" -f $(if ($bernerDateReady) { 'PASS candidate / receive date -> BC Shipment Date for exact Berner profile' } else { 'REVIEW' }))
Write-Host ("Herdez date semantics  : {0}" -f $(if ($herdezDateReady) { 'PASS candidate / source Delivery Date -> BC Requested Delivery Date; BC owns Shipment Date' } else { 'REVIEW' }))
Write-Host "Combined price ready   : $priceAuthorityReady"
Write-Host 'Extension mutation     : NONE'
Write-Host 'Business-data writes   : NONE'
Write-Host 'Sales-order action     : NOT CALLED'
Write-Host 'Write authorization    : NOT GRANTED'
Write-Host 'Production             : HARD BLOCKED'
Write-Host ('=' * 120) -ForegroundColor Cyan

[pscustomobject]@{
    success = $true
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    installedApp = "$ExpectedAppName $ExpectedVersion"
    berner = [pscustomobject]@{
        priceRows = $bernerPriceRows.Count
        latestTwoAgree = $bernerLatestTwoAgree
        resolvedPrice = $bernerResolvedPrice
        sourcePriceCorroborates = $bernerSourceCorroborates
        dateRows = $bernerDateRows.Count
        sourceReceiveEqualsBcShipment = $bernerShipmentDirectMatches
        sourcePoDateEqualsBcOrderDate = $bernerOrderDateDirectMatches
    }
    herdez = [pscustomobject]@{
        sourceLinkedCurrentOrders = $herdezOrderNoSet.Count
        priceRows = $herdezPriceRows.Count
        latestTwoAgree = $herdezLatestTwoAgree
        resolvedPrice = $herdezResolvedPrice
        sourcePriceCorroborates = $herdezSourceCorroborates
        dateRows = $herdezDateRows.Count
        sourceDeliveryEqualsBcRequested = $herdezRequestedMatches
        sourceDeliveryEqualsBcShipment = $herdezShipmentDirectMatches
        sourcePoDateEqualsBcOrderDate = $herdezOrderDateDirectMatches
    }
    priceAuthorityReady = $priceAuthorityReady
    writeAuthorization = 'NOT_GRANTED'
    safety = [pscustomobject]@{
        extensionMutation = 'NONE'
        businessDataReads = 'GET_ONLY'
        businessDataWrites = 'NONE'
        salesOrderAction = 'NOT_CALLED'
        releaseShipInvoicePost = 'NOT_CALLED_BLOCKED'
        production = 'HARD_BLOCKED'
    }
} | ConvertTo-Json -Depth 10
