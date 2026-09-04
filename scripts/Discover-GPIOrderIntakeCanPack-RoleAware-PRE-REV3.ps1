#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# PRE-ONLY / GET-ONLY CANPACK ROLE-AWARE DISCOVERY
#
# Evidence correction:
# - CanPack operating procedures identify Can Pack as vendor/manufacturer and describe processing a Purchase Order.
# - Drop-ship procedures separately reference the linked Sales Order for the end customer.
# - Therefore this script searches CanPack as a VENDOR and treats workbook product/material values as supplier-side clues.
# - New Glarus / customer NEW is a targeted end-customer candidate only for the Spotted Cow rows; it is not generalized
#   to every row in the workbook.
#
# No extension mutation. No business-data writes. No Sales Order action.
# =====================================================================================================================
$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$CompanyId         = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'
$ExpectedAppId     = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$ExpectedAppName   = 'GPI Order Intake'
$ExpectedPublisher = 'Gamer Packaging Inc'
$ExpectedVersion   = '0.1.0.8'

$VendorClues = @('CANPACK','CAN PACK')
$SpottedCowCustomerNo = 'NEW'
$SpottedCowCustomerName = 'New Glarus Brewing Company'
$SupplierMaterialRefs = @('BRITE','3286_NH01','3286-OK02','3286-OJ02')
$SupplierPlant = 'US50'
$KnownCanpackBcLocationCodes = @('917','918')

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
    Assert-BcUri $Uri
    Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 120
}

function Invoke-BcGetAll {
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers,[int]$MaxPages=100)
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
    return ([regex]::Replace($Value.ToUpperInvariant(),'[^A-Z0-9]',''))
}

if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company pin changed.' }

$token = Get-BcToken
$headers = @{Authorization="Bearer $token";Accept='application/json'}
$envs = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $headers
$envMatch = @($envs.value | Where-Object {[string]$_.name -eq $Environment})
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

Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - CANPACK ROLE-AWARE DISCOVERY REV3 / PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "Environment        : $Environment"
Write-Host "Environment type   : $environmentType"
Write-Host "Company            : $CompanyName"
Write-Host "Installed app      : $ExpectedAppName $ExpectedVersion"
Write-Host 'Classification     : CanPack workbook = supplier/manufacturer schedule evidence, not customer identity'
Write-Host "Targeted row proof : Spotted Cow -> candidate end-customer $SpottedCowCustomerNo / $SpottedCowCustomerName only"
Write-Host "Supplier refs       : $($SupplierMaterialRefs -join ', ')"
Write-Host "Supplier plant      : $SupplierPlant (source facility only; not BC Location)"
Write-Host 'HTTP methods       : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation : NONE' -ForegroundColor Green
Write-Host 'Business data write: NONE' -ForegroundColor Green
Write-Host 'Sales-order action : NOT CALLED' -ForegroundColor Green
Write-Host 'Production         : HARD BLOCKED' -ForegroundColor Green
Write-Host ('='*120) -ForegroundColor Cyan

$customerSelect = [Uri]::EscapeDataString('id,number,displayName,addressLine1,addressLine2,city,state,country,postalCode,blocked')
$vendorSelect = [Uri]::EscapeDataString('id,number,displayName,addressLine1,addressLine2,city,state,country,postalCode,blocked')
$itemSelect = [Uri]::EscapeDataString('id,number,displayName,type,blocked,baseUnitOfMeasureCode')
$locationSelect = [Uri]::EscapeDataString('id,code,displayName,addressLine1,addressLine2,city,state,country,postalCode')

$customers = @(Invoke-BcGetAll "$companyRoot/customers?`$select=$customerSelect&`$top=200" $headers)
$vendors = @(Invoke-BcGetAll "$companyRoot/vendors?`$select=$vendorSelect&`$top=200" $headers)
$items = @(Invoke-BcGetAll "$companyRoot/items?`$select=$itemSelect&`$top=200" $headers)
$locations = @(Invoke-BcGetAll "$companyRoot/locations?`$select=$locationSelect&`$top=200" $headers)

$canpackVendors = @($vendors | Where-Object {
    $text = ([string]$_.number + ' ' + [string]$_.displayName).ToUpperInvariant()
    @($VendorClues | Where-Object {$text.Contains($_)}).Count -gt 0
})

$newGlarus = @($customers | Where-Object {
    [string]$_.number -eq $SpottedCowCustomerNo -or [string]$_.displayName -eq $SpottedCowCustomerName
})

$normalizedSupplierRefs = @{}
foreach ($ref in $SupplierMaterialRefs) { $normalizedSupplierRefs[$ref] = Normalize-Key $ref }

$directItemMatches = [System.Collections.Generic.List[object]]::new()
foreach ($item in $items) {
    $itemNoNorm = Normalize-Key ([string]$item.number)
    $itemNameNorm = Normalize-Key ([string]$item.displayName)
    foreach ($entry in $normalizedSupplierRefs.GetEnumerator()) {
        $clueNorm = [string]$entry.Value
        if ([string]::IsNullOrWhiteSpace($clueNorm)) { continue }
        if ($itemNoNorm.Contains($clueNorm) -or $clueNorm.Contains($itemNoNorm) -or $itemNameNorm.Contains($clueNorm)) {
            $directItemMatches.Add([pscustomobject][ordered]@{
                supplierReference=[string]$entry.Key
                itemNumber=[string]$item.number
                itemName=[string]$item.displayName
                baseUom=[string]$item.baseUnitOfMeasureCode
                blocked=$item.blocked
            })
        }
    }
}

Write-Host ''
Write-Host 'CANPACK_VENDOR_CANDIDATES' -ForegroundColor Cyan
foreach ($v in $canpackVendors) {
    Write-Host ('VENDOR_CANDIDATE|number={0}|name={1}|city={2}|state={3}|blocked={4}' -f $v.number,$v.displayName,$v.city,$v.state,$v.blocked)
}
if ($canpackVendors.Count -eq 0) { Write-Host 'VENDOR_CANDIDATE|NONE' -ForegroundColor Yellow }

Write-Host ''
Write-Host 'SPOTTED_COW_END_CUSTOMER_CANDIDATE' -ForegroundColor Cyan
foreach ($c in $newGlarus) {
    Write-Host ('END_CUSTOMER_CANDIDATE|number={0}|name={1}|city={2}|state={3}|blocked={4}' -f $c.number,$c.displayName,$c.city,$c.state,$c.blocked)
}
if ($newGlarus.Count -eq 0) { Write-Host 'END_CUSTOMER_CANDIDATE|NONE' -ForegroundColor Yellow }

Write-Host ''
Write-Host 'NORMALIZED_SUPPLIER_REFERENCE_ITEM_MATCHES' -ForegroundColor Cyan
foreach ($m in $directItemMatches) {
    Write-Host ('SUPPLIER_REF_ITEM_MATCH|sourceRef={0}|item={1}|name={2}|baseUom={3}|blocked={4}' -f $m.supplierReference,$m.itemNumber,$m.itemName,$m.baseUom,$m.blocked)
}
if ($directItemMatches.Count -eq 0) { Write-Host 'SUPPLIER_REF_ITEM_MATCH|NONE' -ForegroundColor Yellow }

$history = @()
if ($newGlarus.Count -eq 1) {
    $custLit = Escape-ODataLiteral ([string]$newGlarus[0].number)
    $filter = [Uri]::EscapeDataString("sellToCustomerNumber eq '$custLit'")
    $history = @(Invoke-BcGetAll "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$filter&`$top=200" $headers)
}

$itemIndex = @{}
foreach ($i in $items) { $itemIndex[[string]$i.number] = $i }
$historyGroups = [System.Collections.Generic.List[object]]::new()
foreach ($g in @($history | Group-Object itemNumber)) {
    $itemNo = [string]$g.Name
    if ([string]::IsNullOrWhiteSpace($itemNo)) { continue }
    $rows = @($g.Group | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
    $detail = if ($itemIndex.ContainsKey($itemNo)) { $itemIndex[$itemNo] } else { $null }
    $historyGroups.Add([pscustomobject][ordered]@{
        itemNumber=$itemNo
        itemName=if ($detail) {[string]$detail.displayName} else {''}
        rowCount=$rows.Count
        latestDocument=[string]$rows[0].documentNumber
        latestCreatedAt=[string]$rows[0].systemCreatedAt
        latestQuantity=[decimal]$rows[0].quantity
        latestUom=[string]$rows[0].unitOfMeasureCode
        latestLocation=[string]$rows[0].locationCode
        latestPrice=[decimal]$rows[0].unitPrice
        observedUoms=@($rows | ForEach-Object {[string]$_.unitOfMeasureCode} | Sort-Object -Unique)
        observedLocations=@($rows | ForEach-Object {[string]$_.locationCode} | Sort-Object -Unique)
    })
}

$historyDirectMatches = @($historyGroups | Where-Object {
    $groupNorm = Normalize-Key ($_.itemNumber + ' ' + $_.itemName)
    $hit = $false
    foreach ($entry in $normalizedSupplierRefs.GetEnumerator()) {
        $clueNorm = [string]$entry.Value
        if (-not [string]::IsNullOrWhiteSpace($clueNorm) -and ($groupNorm.Contains($clueNorm) -or $clueNorm.Contains((Normalize-Key $_.itemNumber)))) {
            $hit = $true
        }
    }
    $hit -or ([string]$_.itemName).ToUpperInvariant().Contains('SPOTTED')
})

Write-Host ''
Write-Host 'NEW_GLARUS_HISTORY_DIRECT_MATCHES' -ForegroundColor Cyan
foreach ($h in $historyDirectMatches | Sort-Object itemNumber) {
    Write-Host ('NEW_HISTORY_MATCH|item={0}|name={1}|rows={2}|latestQty={3}|uom={4}|location={5}|price={6}|uoms={7}|locations={8}' -f
        $h.itemNumber,$h.itemName,$h.rowCount,$h.latestQuantity,$h.latestUom,$h.latestLocation,$h.latestPrice,
        ($h.observedUoms -join ','),($h.observedLocations -join ','))
}
if ($historyDirectMatches.Count -eq 0) { Write-Host 'NEW_HISTORY_MATCH|NONE' -ForegroundColor Yellow }

Write-Host ''
Write-Host 'NEW_GLARUS_RECENT_ITEM_CONTEXTS_TOP25' -ForegroundColor Cyan
foreach ($h in @($historyGroups | Sort-Object {[DateTimeOffset]$_.latestCreatedAt} -Descending | Select-Object -First 25)) {
    Write-Host ('NEW_RECENT_ITEM|item={0}|name={1}|rows={2}|latest={3}|qty={4}|uom={5}|location={6}|price={7}' -f
        $h.itemNumber,$h.itemName,$h.rowCount,$h.latestCreatedAt,$h.latestQuantity,$h.latestUom,$h.latestLocation,$h.latestPrice)
}
if ($historyGroups.Count -eq 0) { Write-Host 'NEW_RECENT_ITEM|NONE' -ForegroundColor Yellow }

$candidateItemNos = @(
    @($directItemMatches | ForEach-Object {[string]$_.itemNumber}) +
    @($historyDirectMatches | ForEach-Object {[string]$_.itemNumber})
) | Where-Object {-not [string]::IsNullOrWhiteSpace($_)} | Sort-Object -Unique

Write-Host ''
Write-Host 'CONFIGURED_UOM_FOR_MATCHED_ITEMS' -ForegroundColor Cyan
$uomCount = 0
foreach ($itemNo in $candidateItemNos) {
    $itemLit = Escape-ODataLiteral $itemNo
    $filter = [Uri]::EscapeDataString("itemNumber eq '$itemLit'")
    $uoms = @(Invoke-BcGetAll "$customRoot/orderIntakeItemUnitsOfMeasure?`$filter=$filter&`$top=200" $headers)
    foreach ($u in $uoms) {
        $uomCount++
        Write-Host ('MATCHED_ITEM_UOM|item={0}|code={1}|qtyPerUom={2}|rounding={3}' -f
            $itemNo,$u.code,$u.quantityPerUnitOfMeasure,$u.quantityRoundingPrecision)
    }
}
if ($uomCount -eq 0) { Write-Host 'MATCHED_ITEM_UOM|NONE' -ForegroundColor Yellow }

Write-Host ''
Write-Host 'CANPACK_LOCATION_CONTEXT' -ForegroundColor Cyan
foreach ($l in $locations | Where-Object {
    [string]$_.code -in $KnownCanpackBcLocationCodes -or
    (([string]$_.code + ' ' + [string]$_.displayName).ToUpperInvariant().Contains($SupplierPlant))
}) {
    Write-Host ('LOCATION_CONTEXT|code={0}|name={1}|city={2}|state={3}|sourcePlantExactTextHit={4}' -f
        $l.code,$l.displayName,$l.city,$l.state,
        (([string]$l.code + ' ' + [string]$l.displayName).ToUpperInvariant().Contains($SupplierPlant)))
}

$vendorStatus = if ($canpackVendors.Count -eq 1) {'RESOLVED_UNIQUE_VENDOR'} elseif ($canpackVendors.Count -gt 1) {'AMBIGUOUS_VENDOR'} else {'UNRESOLVED_VENDOR'}
$spottedCustomerStatus = if ($newGlarus.Count -eq 1) {'RESOLVED_TARGETED_END_CUSTOMER'} elseif ($newGlarus.Count -gt 1) {'AMBIGUOUS_END_CUSTOMER'} else {'UNRESOLVED_END_CUSTOMER'}
$materialStatus = if ($directItemMatches.Count -gt 0 -or $historyDirectMatches.Count -gt 0) {'CANDIDATE_MATCHES_FOUND_REVIEW_REQUIRED'} else {'UNRESOLVED'}

Write-Host ''
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'CANPACK ROLE-AWARE DISCOVERY CONCLUSION' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "CanPack party role             : SUPPLIER / MANUFACTURER"
Write-Host "CanPack vendor status          : $vendorStatus"
Write-Host "Spotted Cow end-customer status: $spottedCustomerStatus"
Write-Host "Supplier material mapping      : $materialStatus"
Write-Host "Supplier plant $SupplierPlant            : SOURCE FACILITY ONLY; NOT MAPPED TO BC LOCATION BY ASSUMPTION"
Write-Host 'Workbook-level sell-to customer: NOT VALID - row/link-level resolution required'
Write-Host 'Write authorization             : NOT GRANTED' -ForegroundColor Green
Write-Host 'Sales-order action              : NOT CALLED' -ForegroundColor Green
Write-Host 'Production                      : HARD BLOCKED' -ForegroundColor Green
Write-Host ('='*120) -ForegroundColor Cyan

[ordered]@{
    success=$true
    canpackPartyRole='SUPPLIER_MANUFACTURER'
    vendorStatus=$vendorStatus
    vendorCandidates=@($canpackVendors)
    spottedCowEndCustomerStatus=$spottedCustomerStatus
    spottedCowEndCustomerCandidates=@($newGlarus)
    supplierMaterialReferences=$SupplierMaterialRefs
    directItemMatches=@($directItemMatches)
    newGlarusHistoryDirectMatches=@($historyDirectMatches)
    sourceFacilityReference=$SupplierPlant
    writeAuthorization='NOT_GRANTED'
    safety=[ordered]@{
        httpMethods=@('GET')
        extensionMutation='NONE'
        businessDataWrites='NONE'
        salesOrderAction='NOT_CALLED'
        production='HARD_BLOCKED'
    }
} | ConvertTo-Json -Depth 20
