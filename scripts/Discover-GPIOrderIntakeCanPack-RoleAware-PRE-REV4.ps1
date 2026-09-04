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

# Evidence-backed keys only. CANPUSA is documented for Can-Pack Olyphant.
# The additional CanPack vendor numbers are from Gamer's current routing evidence and are probes, not assumptions
# that the source workbook belongs to any one of them.
$KnownCanpackVendorNos = @('CANPUSA','CANPACK','CANPCOL','CANPIND','CANPMID','CANPNETH')
$SpottedCowCustomerNo  = 'NEW'
$SupplierMaterialRefs  = @('3286_NH01','3286-OK02','3286-OJ02')
$GenericProductClue    = 'BRITE'
$SourceFacilityRef     = 'US50'
$KnownCanpackLocationCodes = @('917','918')

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
    return [regex]::Replace($Value.ToUpperInvariant(),'[^A-Z0-9]','')
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

Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - CANPACK ROLE-AWARE DISCOVERY REV4 / PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "Environment        : $Environment"
Write-Host "Environment type   : $environmentType"
Write-Host "Company            : $CompanyName"
Write-Host "Installed app      : $ExpectedAppName $ExpectedVersion"
Write-Host 'Classification     : supplier/manufacturer schedule evidence; NOT workbook-level customer identity'
Write-Host "Exact vendor probes : $($KnownCanpackVendorNos -join ', ')"
Write-Host "Spotted Cow probe   : customer $SpottedCowCustomerNo; history queried regardless of customer-master result"
Write-Host "Material refs       : $($SupplierMaterialRefs -join ', ') (item-number matching only)"
Write-Host "Generic clue        : $GenericProductClue (description evidence only; never identity)"
Write-Host "Source facility     : $SourceFacilityRef (not a BC Location by assumption)"
Write-Host 'HTTP methods        : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation  : NONE' -ForegroundColor Green
Write-Host 'Business data write : NONE' -ForegroundColor Green
Write-Host 'Sales-order action  : NOT CALLED' -ForegroundColor Green
Write-Host 'Production          : HARD BLOCKED' -ForegroundColor Green
Write-Host ('='*120) -ForegroundColor Cyan

$vendorSelect = [Uri]::EscapeDataString('id,number,displayName,addressLine1,addressLine2,city,state,country,postalCode,blocked')
$customerSelect = [Uri]::EscapeDataString('id,number,displayName,addressLine1,addressLine2,city,state,country,postalCode,blocked')
$itemSelect = [Uri]::EscapeDataString('id,number,displayName,type,blocked,baseUnitOfMeasureCode')
$locationSelect = [Uri]::EscapeDataString('id,code,displayName,addressLine1,addressLine2,city,state,country,postalCode')

Write-Host ''
Write-Host 'EXACT_CANPACK_VENDOR_NUMBER_PROBES' -ForegroundColor Cyan
$vendorProbeRows = [System.Collections.Generic.List[object]]::new()
foreach ($vendorNo in $KnownCanpackVendorNos) {
    $lit = Escape-ODataLiteral $vendorNo
    $filter = [Uri]::EscapeDataString("number eq '$lit'")
    $rows = @(Invoke-BcGetAll "$companyRoot/vendors?`$select=$vendorSelect&`$filter=$filter&`$top=200" $headers)
    if ($rows.Count -eq 0) {
        Write-Host "VENDOR_NUMBER_PROBE|number=$vendorNo|matches=0"
    }
    foreach ($v in $rows) {
        $vendorProbeRows.Add($v)
        Write-Host ('VENDOR_NUMBER_PROBE|number={0}|matches={1}|name={2}|city={3}|state={4}|blocked={5}' -f $vendorNo,$rows.Count,$v.displayName,$v.city,$v.state,$v.blocked)
    }
}

Write-Host ''
Write-Host 'EXACT_NEW_GLARUS_CUSTOMER_NUMBER_PROBE' -ForegroundColor Cyan
$newLit = Escape-ODataLiteral $SpottedCowCustomerNo
$newFilter = [Uri]::EscapeDataString("number eq '$newLit'")
$newCustomerRows = @(Invoke-BcGetAll "$companyRoot/customers?`$select=$customerSelect&`$filter=$newFilter&`$top=200" $headers)
if ($newCustomerRows.Count -eq 0) {
    Write-Host "END_CUSTOMER_NUMBER_PROBE|number=$SpottedCowCustomerNo|matches=0"
}
foreach ($c in $newCustomerRows) {
    Write-Host ('END_CUSTOMER_NUMBER_PROBE|number={0}|matches={1}|name={2}|city={3}|state={4}|blocked={5}' -f $SpottedCowCustomerNo,$newCustomerRows.Count,$c.displayName,$c.city,$c.state,$c.blocked)
}

# Load the full item master only for deterministic normalized item-number comparison.
$items = @(Invoke-BcGetAll "$companyRoot/items?`$select=$itemSelect&`$top=200" $headers)
$itemIndex = @{}
foreach ($item in $items) {
    $no = [string]$item.number
    if (-not [string]::IsNullOrWhiteSpace($no)) { $itemIndex[$no] = $item }
}

Write-Host ''
Write-Host 'SUPPLIER_REFERENCE_TO_BC_ITEM_NUMBER_CANDIDATES' -ForegroundColor Cyan
$directItemMatches = [System.Collections.Generic.List[object]]::new()
foreach ($sourceRef in $SupplierMaterialRefs) {
    $sourceNorm = Normalize-Key $sourceRef
    $matches = @($items | Where-Object {
        $itemNo = [string]$_.number
        if ([string]::IsNullOrWhiteSpace($itemNo)) { return $false }
        $itemNorm = Normalize-Key $itemNo
        if ([string]::IsNullOrWhiteSpace($itemNorm)) { return $false }
        $itemNorm.Contains($sourceNorm) -or $sourceNorm.Contains($itemNorm)
    })
    if ($matches.Count -eq 0) {
        Write-Host "SUPPLIER_REF_ITEM_NUMBER_CANDIDATE|sourceRef=$sourceRef|matches=0"
    }
    foreach ($m in $matches) {
        $directItemMatches.Add([pscustomobject][ordered]@{
            supplierReference=$sourceRef
            itemNumber=[string]$m.number
            itemName=[string]$m.displayName
            baseUom=[string]$m.baseUnitOfMeasureCode
            blocked=$m.blocked
        })
        Write-Host ('SUPPLIER_REF_ITEM_NUMBER_CANDIDATE|sourceRef={0}|matches={1}|item={2}|name={3}|baseUom={4}|blocked={5}' -f $sourceRef,$matches.Count,$m.number,$m.displayName,$m.baseUnitOfMeasureCode,$m.blocked)
    }
}

# BRITE is intentionally not used as an identity key. Show a bounded description-only clue set.
$briteClues = @($items | Where-Object {
    -not [string]::IsNullOrWhiteSpace([string]$_.number) -and
    ([string]$_.displayName).IndexOf($GenericProductClue,[StringComparison]::OrdinalIgnoreCase) -ge 0
} | Select-Object -First 20)
Write-Host ''
Write-Host 'GENERIC_BRITE_DESCRIPTION_CLUES_NOT_IDENTITY' -ForegroundColor Cyan
foreach ($i in $briteClues) {
    Write-Host ('BRITE_DESCRIPTION_CLUE|item={0}|name={1}|baseUom={2}|blocked={3}' -f $i.number,$i.displayName,$i.baseUnitOfMeasureCode,$i.blocked)
}
if ($briteClues.Count -eq 0) { Write-Host 'BRITE_DESCRIPTION_CLUE|NONE' }

# Stronger evidence source: query posted history directly by the known historical customer number NEW.
$historyFilter = [Uri]::EscapeDataString("sellToCustomerNumber eq '$newLit'")
$newHistory = @(Invoke-BcGetAll "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$historyFilter&`$top=200" $headers)
$newRolling = @(Invoke-BcGetAll "$customRoot/orderIntakeCustomerItemSales?`$filter=$historyFilter&`$top=200" $headers)

Write-Host ''
Write-Host 'NEW_GLARUS_POSTED_HISTORY_SUMMARY' -ForegroundColor Cyan
Write-Host "NEW_HISTORY_TOTAL_ROWS=$($newHistory.Count)"

$historyGroups = [System.Collections.Generic.List[object]]::new()
foreach ($g in @($newHistory | Group-Object itemNumber)) {
    $itemNo = [string]$g.Name
    if ([string]::IsNullOrWhiteSpace($itemNo)) { continue }
    $rows = @($g.Group | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
    $detail = if ($itemIndex.ContainsKey($itemNo)) { $itemIndex[$itemNo] } else { $null }
    $historyGroups.Add([pscustomobject][ordered]@{
        itemNumber=$itemNo
        itemName=if ($null -ne $detail) {[string]$detail.displayName} else {''}
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

$historyLikely = @($historyGroups | Where-Object {
    $itemNorm = Normalize-Key ([string]$_.itemNumber)
    $name = [string]$_.itemName
    $materialHit = $false
    foreach ($sourceRef in $SupplierMaterialRefs) {
        $sourceNorm = Normalize-Key $sourceRef
        if (-not [string]::IsNullOrWhiteSpace($itemNorm) -and ($itemNorm.Contains($sourceNorm) -or $sourceNorm.Contains($itemNorm))) {
            $materialHit = $true
        }
    }
    $materialHit -or $name.IndexOf('SPOTTED',[StringComparison]::OrdinalIgnoreCase) -ge 0
} | Sort-Object itemNumber)

Write-Host ''
Write-Host 'NEW_GLARUS_SPOTTED_OR_3286_HISTORY_CANDIDATES' -ForegroundColor Cyan
foreach ($h in $historyLikely) {
    Write-Host ('NEW_HISTORY_CANDIDATE|item={0}|name={1}|rows={2}|latestDoc={3}|latestCreated={4}|latestQty={5}|latestUom={6}|latestLocation={7}|latestPrice={8}|uoms={9}|locations={10}' -f
        $h.itemNumber,$h.itemName,$h.rowCount,$h.latestDocument,$h.latestCreatedAt,$h.latestQuantity,$h.latestUom,$h.latestLocation,$h.latestPrice,
        ($h.observedUoms -join ','),($h.observedLocations -join ','))
}
if ($historyLikely.Count -eq 0) { Write-Host 'NEW_HISTORY_CANDIDATE|NONE' }

Write-Host ''
Write-Host 'NEW_GLARUS_MOST_RECENT_ITEM_CONTEXTS_TOP40' -ForegroundColor Cyan
foreach ($h in @($historyGroups | Sort-Object {[DateTimeOffset]$_.latestCreatedAt} -Descending | Select-Object -First 40)) {
    Write-Host ('NEW_RECENT_ITEM|item={0}|name={1}|rows={2}|latestDoc={3}|latestCreated={4}|latestQty={5}|latestUom={6}|latestLocation={7}|latestPrice={8}' -f
        $h.itemNumber,$h.itemName,$h.rowCount,$h.latestDocument,$h.latestCreatedAt,$h.latestQuantity,$h.latestUom,$h.latestLocation,$h.latestPrice)
}
if ($historyGroups.Count -eq 0) { Write-Host 'NEW_RECENT_ITEM|NONE' }

Write-Host ''
Write-Host 'NEW_GLARUS_BOYER_ROLLING_CONTEXTS' -ForegroundColor Cyan
foreach ($r in $newRolling | Sort-Object itemNumber) {
    Write-Host ('NEW_ROLLING_ITEM|item={0}|lastDate={1}|lastQty={2}|lastUom={3}|lastPrice={4}|location={5}' -f
        $r.itemNumber,$r.lastSoldDate,$r.lastSoldQuantity,$r.lastSoldUnitOfMeasureCode,$r.lastUnitPrice,$r.locationCode)
}
if ($newRolling.Count -eq 0) { Write-Host 'NEW_ROLLING_ITEM|NONE' }

# UOM evidence only for nonblank direct item-number candidates and likely New Glarus history candidates.
$candidateItemNos = @(
    @($directItemMatches | ForEach-Object {[string]$_.itemNumber}) +
    @($historyLikely | ForEach-Object {[string]$_.itemNumber})
) | Where-Object {-not [string]::IsNullOrWhiteSpace($_)} | Sort-Object -Unique

Write-Host ''
Write-Host 'CONFIGURED_UOM_FOR_CANDIDATE_ITEMS' -ForegroundColor Cyan
foreach ($itemNo in $candidateItemNos) {
    $itemLit = Escape-ODataLiteral $itemNo
    $filter = [Uri]::EscapeDataString("itemNumber eq '$itemLit'")
    $uoms = @(Invoke-BcGetAll "$customRoot/orderIntakeItemUnitsOfMeasure?`$filter=$filter&`$top=200" $headers)
    foreach ($u in $uoms) {
        Write-Host ('CANDIDATE_ITEM_UOM|item={0}|code={1}|qtyPerUom={2}|rounding={3}' -f $itemNo,$u.code,$u.quantityPerUnitOfMeasure,$u.quantityRoundingPrecision)
    }
    if ($uoms.Count -eq 0) { Write-Host "CANDIDATE_ITEM_UOM|item=$itemNo|NONE" }
}
if ($candidateItemNos.Count -eq 0) { Write-Host 'CANDIDATE_ITEM_UOM|NONE' }

$locations = @(Invoke-BcGetAll "$companyRoot/locations?`$select=$locationSelect&`$top=200" $headers)
$canpackLocations = @($locations | Where-Object { $KnownCanpackLocationCodes -contains [string]$_.code })
Write-Host ''
Write-Host 'CANPACK_BC_LOCATION_CONTEXT' -ForegroundColor Cyan
foreach ($l in $canpackLocations | Sort-Object code) {
    Write-Host ('LOCATION_CONTEXT|code={0}|name={1}|city={2}|state={3}|sourceFacilityReference={4}|mappingStatus=UNPROVEN' -f
        $l.code,$l.displayName,$l.city,$l.state,$SourceFacilityRef)
}

$vendorStatus = if ($vendorProbeRows.Count -gt 0) { 'EXACT_VENDOR_NUMBER_EVIDENCE_FOUND' } else { 'UNRESOLVED_VENDOR_IN_PRE_STANDARD_API' }
$customerStatus = if ($newCustomerRows.Count -eq 1) {
    'CURRENT_CUSTOMER_MASTER_MATCH'
} elseif ($newHistory.Count -gt 0) {
    'HISTORICAL_POSTED_SALES_EVIDENCE_ONLY'
} else {
    'UNRESOLVED_END_CUSTOMER_IN_PRE'
}
$itemStatus = if ($historyLikely.Count -gt 0) {
    'NEW_HISTORY_CANDIDATES_FOUND_REVIEW_REQUIRED'
} elseif ($directItemMatches.Count -gt 0) {
    'MASTER_ITEM_NUMBER_CANDIDATES_FOUND_REVIEW_REQUIRED'
} else {
    'UNRESOLVED_ITEM_MAPPING'
}

Write-Host ''
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'CANPACK ROLE-AWARE DISCOVERY REV4 CONCLUSION' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'CanPack party role              : SUPPLIER / MANUFACTURER'
Write-Host "CanPack vendor status           : $vendorStatus"
Write-Host "Spotted Cow customer NEW status : $customerStatus"
Write-Host "Supplier material mapping       : $itemStatus"
Write-Host "Supplier facility $SourceFacilityRef        : SOURCE FACILITY ONLY; BC LOCATION MAPPING UNPROVEN"
Write-Host 'Workbook-level sell-to customer : NOT VALID - row/link-level resolution required'
Write-Host 'Write authorization             : NOT GRANTED'
Write-Host 'Sales-order action              : NOT CALLED'
Write-Host 'Production                      : HARD BLOCKED'
Write-Host ('='*120) -ForegroundColor Cyan

[ordered]@{
    success = $true
    canpackPartyRole = 'SUPPLIER_MANUFACTURER'
    exactVendorProbeNumbers = $KnownCanpackVendorNos
    vendorStatus = $vendorStatus
    vendorProbeMatches = @($vendorProbeRows | ForEach-Object {[ordered]@{number=$_.number;name=$_.displayName;city=$_.city;state=$_.state;blocked=$_.blocked}})
    spottedCowCustomerNumber = $SpottedCowCustomerNo
    endCustomerStatus = $customerStatus
    endCustomerMasterMatches = @($newCustomerRows | ForEach-Object {[ordered]@{number=$_.number;name=$_.displayName;city=$_.city;state=$_.state;blocked=$_.blocked}})
    newGlarusPostedHistoryRows = $newHistory.Count
    supplierMaterialReferences = $SupplierMaterialRefs
    directItemNumberMatches = @($directItemMatches)
    newHistoryCandidateItems = @($historyLikely)
    sourceFacilityReference = $SourceFacilityRef
    writeAuthorization = 'NOT_GRANTED'
    safety = [ordered]@{
        httpMethods=@('GET')
        extensionMutation='NONE'
        businessDataWrites='NONE'
        salesOrderAction='NOT_CALLED'
        production='HARD_BLOCKED'
    }
} | ConvertTo-Json -Depth 20
