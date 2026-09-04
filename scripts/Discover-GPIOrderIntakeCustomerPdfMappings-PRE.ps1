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
$ExpectedVersion   = '0.1.0.8'

# Evidence from the real customer-PO corpus and linked Gamer archive documents.
$Berner = [ordered]@{
    CustomerName         = 'Berner Foods'
    CustomerNo           = 'BERNER'          # Proven on Gamer Sales Order 114600 for customer PO 241355.
    CustomerPo           = '241355'
    SourceCustomerItem   = '811476'
    SourceQuantity       = 68000
    SourceUom            = 'EA'
    SourcePrice          = 243.43
    SourcePriceUom       = 'THOU'
    RequestedDate        = '2026-07-20'
    ArchiveSalesOrder    = '114600'
    ArchiveBcItem        = '21759-858231'
    ArchiveBcQuantity    = 72.2
    ArchiveBcUom         = 'M'
    ArchiveBcLocation    = '00'
    ArchiveBcPrice       = 243.43
}

$Herdez = [ordered]@{
    CustomerName         = 'Herdez'
    CustomerPo           = '4500063632'
    SourceVendorRef      = '50001644'
    SourceCustomerItem   = '000000000004003467'
    SourceQuantity       = 195.888
    SourceUom            = 'M'               # Semantic normalization of source `195,888 THOUSAND`.
    SourcePrice          = 225.75
    SourcePriceUom       = 'THOUSAND'
    RequestedDate        = '2026-09-01'
    LinkedGamerPo        = '117357'
    LinkedBcItem         = '20113526'
    LinkedBcQuantity     = 195.888
    LinkedBcUom          = 'M'
}

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
    if ($u.Scheme -ne 'https' -or $u.Host -ne 'api.businesscentral.dynamics.com') { throw "Unexpected URI blocked: $Uri" }
    if ($Uri.IndexOf($ForbiddenEnv,[StringComparison]::OrdinalIgnoreCase) -ge 0) { throw "Forbidden legacy sandbox URI blocked: $Uri" }
    if ($Uri.IndexOf('/Production/',[StringComparison]::OrdinalIgnoreCase) -ge 0) { throw "Production-like URI blocked: $Uri" }
}

function Invoke-BcGet {
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers)
    Assert-BcUri -Uri $Uri
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
    return $Value.Replace("'","''")
}

function Normalize-Key {
    param([AllowNull()][string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    return [regex]::Replace($Value.ToUpperInvariant(),'[^A-Z0-9]','')
}

function Get-CustomerByNumber {
    param([Parameter(Mandatory)][string]$Number)
    $lit = Escape-ODataLiteral $Number
    $filter = [Uri]::EscapeDataString("number eq '$lit'")
    return @(Invoke-BcGetAll "$companyRoot/customers?`$select=$customerSelect&`$filter=$filter&`$top=200" $headers)
}

function Get-ItemByNumber {
    param([Parameter(Mandatory)][string]$Number)
    $lit = Escape-ODataLiteral $Number
    $filter = [Uri]::EscapeDataString("number eq '$lit'")
    return @(Invoke-BcGetAll "$companyRoot/items?`$select=$itemSelect&`$filter=$filter&`$top=200" $headers)
}

function Get-ItemUoms {
    param([Parameter(Mandatory)][string]$ItemNumber)
    $lit = Escape-ODataLiteral $ItemNumber
    $filter = [Uri]::EscapeDataString("itemNumber eq '$lit'")
    return @(Invoke-BcGetAll "$customRoot/orderIntakeItemUnitsOfMeasure?`$filter=$filter&`$top=200" $headers)
}

function Get-History {
    param([Parameter(Mandatory)][string]$CustomerNumber,[Parameter(Mandatory)][string]$ItemNumber)
    $c = Escape-ODataLiteral $CustomerNumber
    $i = Escape-ODataLiteral $ItemNumber
    $filter = [Uri]::EscapeDataString("sellToCustomerNumber eq '$c' and itemNumber eq '$i'")
    return @(Invoke-BcGetAll "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$filter&`$top=200" $headers)
}

function Get-Rolling {
    param([Parameter(Mandatory)][string]$CustomerNumber,[Parameter(Mandatory)][string]$ItemNumber)
    $c = Escape-ODataLiteral $CustomerNumber
    $i = Escape-ODataLiteral $ItemNumber
    $filter = [Uri]::EscapeDataString("sellToCustomerNumber eq '$c' and itemNumber eq '$i'")
    return @(Invoke-BcGetAll "$customRoot/orderIntakeCustomerItemSales?`$filter=$filter&`$top=200" $headers)
}

function Write-ItemContext {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string]$CustomerNumber,
        [Parameter(Mandatory)][string]$ItemNumber
    )

    $itemRows = @(Get-ItemByNumber $ItemNumber)
    if ($itemRows.Count -eq 0) {
        Write-Host "ITEM_CONTEXT|label=$Label|customer=$CustomerNumber|item=$ItemNumber|itemMatches=0"
        return
    }

    foreach ($item in $itemRows) {
        Write-Host ('ITEM_CONTEXT|label={0}|customer={1}|item={2}|itemMatches={3}|name={4}|baseUom={5}|blocked={6}' -f $Label,$CustomerNumber,$ItemNumber,$itemRows.Count,$item.displayName,$item.baseUnitOfMeasureCode,$item.blocked)
    }

    $uoms = @(Get-ItemUoms $ItemNumber | Sort-Object code)
    foreach ($uom in $uoms) {
        Write-Host ('ITEM_UOM|label={0}|item={1}|code={2}|qtyPerUom={3}|rounding={4}' -f $Label,$ItemNumber,$uom.code,$uom.quantityPerUnitOfMeasure,$uom.quantityRoundingPrecision)
    }
    if ($uoms.Count -eq 0) { Write-Host "ITEM_UOM|label=$Label|item=$ItemNumber|NONE" }

    $history = @(Get-History $CustomerNumber $ItemNumber | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
    $rolling = @(Get-Rolling $CustomerNumber $ItemNumber)

    $quantities = @($history | ForEach-Object {[decimal]$_.quantity} | Sort-Object -Unique)
    $uomCodes = @($history | ForEach-Object {[string]$_.unitOfMeasureCode} | Where-Object {-not [string]::IsNullOrWhiteSpace($_)} | Sort-Object -Unique)
    $locations = @($history | ForEach-Object {[string]$_.locationCode} | Sort-Object -Unique)
    $prices = @($history | ForEach-Object {[decimal]$_.unitPrice} | Sort-Object -Unique)

    Write-Host ('HISTORY_SUMMARY|label={0}|customer={1}|item={2}|rows={3}|quantities={4}|uoms={5}|locations={6}|prices={7}' -f $Label,$CustomerNumber,$ItemNumber,$history.Count,($quantities -join ','),($uomCodes -join ','),($locations -join ','),($prices -join ','))

    foreach ($row in @($history | Select-Object -First 5)) {
        Write-Host ('HISTORY_RECENT|label={0}|doc={1}|created={2}|shipDate={3}|qty={4}|uom={5}|location={6}|price={7}' -f $Label,$row.documentNumber,$row.systemCreatedAt,$row.shipmentDate,$row.quantity,$row.unitOfMeasureCode,$row.locationCode,$row.unitPrice)
    }

    foreach ($row in $rolling) {
        Write-Host ('ROLLING|label={0}|customer={1}|item={2}|lastDate={3}|lastQty={4}|lastUom={5}|lastPrice={6}|location={7}' -f $Label,$row.sellToCustomerNumber,$row.itemNumber,$row.lastSoldDate,$row.lastSoldQuantity,$row.lastSoldUnitOfMeasureCode,$row.lastUnitPrice,$row.locationCode)
    }
    if ($rolling.Count -eq 0) { Write-Host "ROLLING|label=$Label|customer=$CustomerNumber|item=$ItemNumber|NONE" }
}

if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company pin changed.' }

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

$envs = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $headers
$envMatch = @($envs.value | Where-Object { [string]$_.name -eq $Environment })
if ($envMatch.Count -ne 1) { throw "Expected exactly one $Environment; found $($envMatch.Count)." }
$environmentType = [string]$envMatch[0].type
if ($environmentType -ine 'sandbox') { throw "SAFETY STOP: environment type is $environmentType." }

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

$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=200" -Headers $headers
$app = @($extensions.value | Where-Object {
    $_.isInstalled -eq $true -and [string]$_.id -eq $ExpectedAppId -and [string]$_.displayName -eq $ExpectedAppName -and
    [string]$_.publisher -eq $ExpectedPublisher -and
    ('{0}.{1}.{2}.{3}' -f $_.versionMajor,$_.versionMinor,$_.versionBuild,$_.versionRevision) -eq $ExpectedVersion
})
if ($app.Count -ne 1) { throw "Expected installed $ExpectedAppName $ExpectedVersion; found $($app.Count)." }

$customerSelect = [Uri]::EscapeDataString('id,number,displayName,addressLine1,addressLine2,city,state,country,postalCode,blocked')
$itemSelect = [Uri]::EscapeDataString('id,number,displayName,type,blocked,baseUnitOfMeasureCode')

Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - CUSTOMER PDF MAPPING DISCOVERY / PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "Environment          : $Environment"
Write-Host "Environment type     : $environmentType"
Write-Host "Company              : $CompanyName"
Write-Host "Company ID           : $CompanyId"
Write-Host "Installed app        : $ExpectedAppName $ExpectedVersion"
Write-Host 'Corpus               : Berner scanned PDF + Herdez Coupa digital PDF'
Write-Host 'Quantity policy      : source quantity immutable evidence; BC quantity requires proven direct/conversion mapping'
Write-Host 'Source price         : evidence/corroboration only; never sent as BC pricing authority'
Write-Host 'HTTP methods         : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation   : NONE' -ForegroundColor Green
Write-Host 'Business data write  : NONE' -ForegroundColor Green
Write-Host 'Sales-order action   : NOT CALLED' -ForegroundColor Green
Write-Host 'Production           : HARD BLOCKED' -ForegroundColor Green
Write-Host ('='*120) -ForegroundColor Cyan

Write-Host ''
Write-Host 'BERNER_ARCHIVE_EVIDENCE' -ForegroundColor Cyan
Write-Host ('BERNER_SOURCE|po={0}|customerItem={1}|sourceQty={2}|sourceUom={3}|sourcePrice={4}|priceUom={5}|requested={6}' -f $Berner.CustomerPo,$Berner.SourceCustomerItem,$Berner.SourceQuantity,$Berner.SourceUom,$Berner.SourcePrice,$Berner.SourcePriceUom,$Berner.RequestedDate)
Write-Host ('BERNER_ARCHIVE_SO|order={0}|customer={1}|item={2}|bcQty={3}|bcUom={4}|location={5}|price={6}' -f $Berner.ArchiveSalesOrder,$Berner.CustomerNo,$Berner.ArchiveBcItem,$Berner.ArchiveBcQuantity,$Berner.ArchiveBcUom,$Berner.ArchiveBcLocation,$Berner.ArchiveBcPrice)
Write-Host 'BERNER_MAPPING_POLICY|status=REVIEW_REQUIRED|reason=source 68000 EA did not historically copy literally to BC 72.2 M; one archived order is evidence of conversion/packout, not enough to define a universal rule'

$bernerCustomer = @(Get-CustomerByNumber $Berner.CustomerNo)
foreach ($c in $bernerCustomer) {
    Write-Host ('CUSTOMER_MATCH|label=BERNER|number={0}|matches={1}|name={2}|city={3}|state={4}|blocked={5}' -f $Berner.CustomerNo,$bernerCustomer.Count,$c.displayName,$c.city,$c.state,$c.blocked)
}
if ($bernerCustomer.Count -eq 0) { Write-Host "CUSTOMER_MATCH|label=BERNER|number=$($Berner.CustomerNo)|matches=0" }

$allCustomers = @(Invoke-BcGetAll "$companyRoot/customers?`$select=$customerSelect&`$top=200" $headers)
$herdezCustomers = @($allCustomers | Where-Object {
    (Normalize-Key ([string]$_.displayName)).Contains('HERDEZ') -or (Normalize-Key ([string]$_.number)).Contains('HERDEZ')
})
Write-Host ''
Write-Host 'HERDEZ_CUSTOMER_DISCOVERY' -ForegroundColor Cyan
foreach ($c in $herdezCustomers) {
    Write-Host ('CUSTOMER_MATCH|label=HERDEZ|number={0}|matches={1}|name={2}|city={3}|state={4}|blocked={5}' -f $c.number,$herdezCustomers.Count,$c.displayName,$c.city,$c.state,$c.blocked)
}
if ($herdezCustomers.Count -eq 0) { Write-Host 'CUSTOMER_MATCH|label=HERDEZ|matches=0' }

Write-Host ''
Write-Host 'DIRECT_SOURCE_ITEM_NUMBER_PROBES' -ForegroundColor Cyan
foreach ($probe in @(
    [pscustomobject]@{Label='BERNER_SOURCE_REF';Number=$Berner.SourceCustomerItem},
    [pscustomobject]@{Label='HERDEZ_SOURCE_REF';Number=$Herdez.SourceCustomerItem}
)) {
    $rows = @(Get-ItemByNumber $probe.Number)
    if ($rows.Count -eq 0) {
        Write-Host "DIRECT_ITEM_PROBE|label=$($probe.Label)|sourceRef=$($probe.Number)|matches=0"
    }
    foreach ($row in $rows) {
        Write-Host ('DIRECT_ITEM_PROBE|label={0}|sourceRef={1}|matches={2}|item={3}|name={4}|baseUom={5}|blocked={6}' -f $probe.Label,$probe.Number,$rows.Count,$row.number,$row.displayName,$row.baseUnitOfMeasureCode,$row.blocked)
    }
}

Write-Host ''
Write-Host 'ARCHIVE_LINKED_BC_ITEM_CONTEXTS' -ForegroundColor Cyan
Write-ItemContext -Label 'BERNER_ARCHIVE_ITEM' -CustomerNumber $Berner.CustomerNo -ItemNumber $Berner.ArchiveBcItem

$resolvedHerdezCustomerNo = $null
if ($herdezCustomers.Count -eq 1) { $resolvedHerdezCustomerNo = [string]$herdezCustomers[0].number }
if (-not [string]::IsNullOrWhiteSpace($resolvedHerdezCustomerNo)) {
    Write-Host ('HERDEZ_SOURCE|po={0}|vendorRef={1}|customerItem={2}|sourceQty={3}|sourceUom={4}|sourcePrice={5}|priceUom={6}|requested={7}' -f $Herdez.CustomerPo,$Herdez.SourceVendorRef,$Herdez.SourceCustomerItem,$Herdez.SourceQuantity,$Herdez.SourceUom,$Herdez.SourcePrice,$Herdez.SourcePriceUom,$Herdez.RequestedDate)
    Write-Host ('HERDEZ_LINKED_GAMER_PO|po={0}|item={1}|qty={2}|uom={3}' -f $Herdez.LinkedGamerPo,$Herdez.LinkedBcItem,$Herdez.LinkedBcQuantity,$Herdez.LinkedBcUom)
    Write-ItemContext -Label 'HERDEZ_LINKED_ITEM' -CustomerNumber $resolvedHerdezCustomerNo -ItemNumber $Herdez.LinkedBcItem
} else {
    Write-Host "HERDEZ_LINKED_ITEM|SKIPPED|reason=expected exactly one Herdez customer candidate; found $($herdezCustomers.Count)"
}

Write-Host ''
Write-Host 'CUSTOMER_SHIP_TO_DISCOVERY' -ForegroundColor Cyan
try {
    $shipTos = @(Invoke-BcGetAll "$companyRoot/customerShippingAddresses?`$top=200" $headers)
    Write-Host "CUSTOMER_SHIP_TO_ENDPOINT|status=AVAILABLE|rows=$($shipTos.Count)"
    foreach ($target in @(
        [pscustomobject]@{Label='BERNER';Customers=$bernerCustomer},
        [pscustomobject]@{Label='HERDEZ';Customers=$herdezCustomers}
    )) {
        foreach ($customer in @($target.Customers)) {
            $rows = @($shipTos | Where-Object {[string]$_.customerId -eq [string]$customer.id})
            foreach ($s in $rows) {
                Write-Host ('SHIP_TO|label={0}|customer={1}|code={2}|name={3}|address1={4}|city={5}|state={6}|postal={7}|country={8}' -f $target.Label,$customer.number,$s.code,$s.displayName,$s.addressLine1,$s.city,$s.state,$s.postalCode,$s.country)
            }
            if ($rows.Count -eq 0) { Write-Host "SHIP_TO|label=$($target.Label)|customer=$($customer.number)|NONE" }
        }
    }
}
catch {
    Write-Host ('CUSTOMER_SHIP_TO_ENDPOINT|status=UNAVAILABLE|message={0}' -f $_.Exception.Message)
}

Write-Host ''
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'CUSTOMER PDF MAPPING DISCOVERY CONCLUSION' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'Berner quantity mapping : REVIEW until repeated customer/item conversion evidence defines 68k-EA-style PO quantities vs BC M packout.'
Write-Host 'Herdez quantity mapping : candidate direct semantic mapping only; require exact customer + item + configured UOM + sales-history corroboration from output.'
Write-Host 'Customer item refs      : source references remain evidence unless direct item/cross-reference linkage is proven.'
Write-Host 'Source prices           : comparison evidence only; BC remains pricing authority.'
Write-Host 'Write authorization     : NOT GRANTED by this script.'
Write-Host 'Sales-order action      : NOT CALLED.'
Write-Host 'Production              : HARD BLOCKED.'
Write-Host ('='*120) -ForegroundColor Cyan
