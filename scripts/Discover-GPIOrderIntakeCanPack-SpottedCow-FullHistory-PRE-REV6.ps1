#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# PRE-only / GET-only targeted discovery for the CanPack Spotted Cow row.
# This deliberately removes the prior $top=200 total-result cap from New Glarus posted-history evidence.
# It does not authorize or invoke any Sales Order action.

$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$CompanyId         = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'
$ExpectedAppId     = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$ExpectedAppName   = 'GPI Order Intake'
$ExpectedPublisher = 'Gamer Packaging Inc'
$ExpectedVersion   = '0.1.0.8'

$CanPackVendorNo       = 'CANPUSA'
$NewGlarusCustomerNo   = 'NEW'
$SourceMaterialRef     = '3286_NH01'
$SourceFacilityRef     = 'US50'
$FamilyPrefix          = '3286-NH'
$KnownLocationCodes    = @('917','918')

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
$companyRoot = "$standardRoot/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"
$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"

$companies = Invoke-BcGet -Uri "$standardRoot/companies" -Headers $headers
$companyMatch = @($companies.value | Where-Object {
    [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatch.Count -ne 1) { throw "Exact Gamer Packaging company verification failed; found $($companyMatch.Count)." }

$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=200" -Headers $headers
$app = @($extensions.value | Where-Object {
    $_.isInstalled -eq $true -and [string]$_.id -eq $ExpectedAppId -and [string]$_.displayName -eq $ExpectedAppName -and
    [string]$_.publisher -eq $ExpectedPublisher -and
    ('{0}.{1}.{2}.{3}' -f $_.versionMajor,$_.versionMinor,$_.versionBuild,$_.versionRevision) -eq $ExpectedVersion
})
if ($app.Count -ne 1) { throw "Expected installed $ExpectedAppName $ExpectedVersion; found $($app.Count)." }

Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - CANPACK SPOTTED COW FULL-HISTORY DISCOVERY REV6 / PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "Environment          : $Environment"
Write-Host "Environment type     : $environmentType"
Write-Host "Company              : $CompanyName"
Write-Host "Installed app        : $ExpectedAppName $ExpectedVersion"
Write-Host "Vendor probe         : $CanPackVendorNo"
Write-Host "End-customer probe   : $NewGlarusCustomerNo"
Write-Host "Source material ref  : $SourceMaterialRef"
Write-Host "BC family under test : $FamilyPrefix*"
Write-Host "Source facility      : $SourceFacilityRef (mapping still unproven)"
Write-Host 'History query        : FULL customer history; NO $top total-result cap' -ForegroundColor Green
Write-Host 'HTTP methods         : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation   : NONE' -ForegroundColor Green
Write-Host 'Business data write  : NONE' -ForegroundColor Green
Write-Host 'Sales-order action   : NOT CALLED' -ForegroundColor Green
Write-Host 'Production           : HARD BLOCKED' -ForegroundColor Green
Write-Host ('='*120) -ForegroundColor Cyan

$vendorSelect = [Uri]::EscapeDataString('id,number,displayName,city,state,blocked')
$customerSelect = [Uri]::EscapeDataString('id,number,displayName,city,state,blocked')
$locationSelect = [Uri]::EscapeDataString('id,code,displayName,city,state')

$vendorLit = Escape-ODataLiteral $CanPackVendorNo
$vendorFilter = [Uri]::EscapeDataString("number eq '$vendorLit'")
$vendorRows = @(Invoke-BcGetAll "$companyRoot/vendors?`$select=$vendorSelect&`$filter=$vendorFilter" $headers)
Write-Host ''
Write-Host 'CANPACK_VENDOR_PROOF' -ForegroundColor Cyan
foreach ($v in $vendorRows) {
    Write-Host ('CANPACK_VENDOR|number={0}|name={1}|city={2}|state={3}|blocked={4}' -f $v.number,$v.displayName,$v.city,$v.state,$v.blocked)
}
if ($vendorRows.Count -eq 0) { Write-Host 'CANPACK_VENDOR|NONE' }

$customerLit = Escape-ODataLiteral $NewGlarusCustomerNo
$customerFilter = [Uri]::EscapeDataString("number eq '$customerLit'")
$customerRows = @(Invoke-BcGetAll "$companyRoot/customers?`$select=$customerSelect&`$filter=$customerFilter" $headers)
Write-Host ''
Write-Host 'NEW_GLARUS_CUSTOMER_PROOF' -ForegroundColor Cyan
foreach ($c in $customerRows) {
    Write-Host ('NEW_CUSTOMER|number={0}|name={1}|city={2}|state={3}|blocked={4}' -f $c.number,$c.displayName,$c.city,$c.state,$c.blocked)
}
if ($customerRows.Count -eq 0) { Write-Host 'NEW_CUSTOMER|NONE' }

# Critical correction from REV4/REV5: no $top on posted history.
$historyFilter = [Uri]::EscapeDataString("sellToCustomerNumber eq '$customerLit'")
$history = @(Invoke-BcGetAll "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$historyFilter" $headers)
$rolling = @(Invoke-BcGetAll "$customRoot/orderIntakeCustomerItemSales?`$filter=$historyFilter" $headers)

$historyCreated = @($history | ForEach-Object {
    if (-not [string]::IsNullOrWhiteSpace([string]$_.systemCreatedAt)) { [DateTimeOffset]$_.systemCreatedAt }
})
$historyNewest = if ($historyCreated.Count -gt 0) { ($historyCreated | Sort-Object -Descending | Select-Object -First 1).ToString('o') } else { '' }
$historyOldest = if ($historyCreated.Count -gt 0) { ($historyCreated | Sort-Object | Select-Object -First 1).ToString('o') } else { '' }

Write-Host ''
Write-Host 'NEW_GLARUS_FULL_HISTORY_SUMMARY' -ForegroundColor Cyan
Write-Host "NEW_FULL_HISTORY_TOTAL_ROWS=$($history.Count)"
Write-Host "NEW_FULL_HISTORY_NEWEST_CREATED=$historyNewest"
Write-Host "NEW_FULL_HISTORY_OLDEST_CREATED=$historyOldest"
Write-Host "NEW_ROLLING_TOTAL_ROWS=$($rolling.Count)"

$familyHistory = @($history | Where-Object {
    $item = [string]$_.itemNumber
    -not [string]::IsNullOrWhiteSpace($item) -and $item.StartsWith($FamilyPrefix,[StringComparison]::OrdinalIgnoreCase)
})

$familyGroups = @($familyHistory | Group-Object itemNumber | ForEach-Object {
    $rows = @($_.Group | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
    $latest = if ($rows.Count -ge 1) { $rows[0] } else { $null }
    $second = if ($rows.Count -ge 2) { $rows[1] } else { $null }
    [pscustomobject][ordered]@{
        itemNumber=[string]$_.Name
        rowCount=$rows.Count
        latestDocument=if ($null -ne $latest) {[string]$latest.documentNumber} else {''}
        latestCreatedAt=if ($null -ne $latest) {[string]$latest.systemCreatedAt} else {''}
        latestQuantity=if ($null -ne $latest) {[decimal]$latest.quantity} else {0}
        latestUom=if ($null -ne $latest) {[string]$latest.unitOfMeasureCode} else {''}
        latestLocation=if ($null -ne $latest) {[string]$latest.locationCode} else {''}
        latestPrice=if ($null -ne $latest) {[decimal]$latest.unitPrice} else {0}
        secondDocument=if ($null -ne $second) {[string]$second.documentNumber} else {''}
        secondCreatedAt=if ($null -ne $second) {[string]$second.systemCreatedAt} else {''}
        secondPrice=if ($null -ne $second) {[decimal]$second.unitPrice} else {0}
        observedQuantities=@($rows | ForEach-Object {[decimal]$_.quantity} | Sort-Object -Unique)
        observedUoms=@($rows | ForEach-Object {[string]$_.unitOfMeasureCode} | Sort-Object -Unique)
        observedLocations=@($rows | ForEach-Object {[string]$_.locationCode} | Sort-Object -Unique)
    }
} | Sort-Object {[DateTimeOffset]$_.latestCreatedAt} -Descending)

Write-Host ''
Write-Host 'NEW_GLARUS_3286_NH_FULL_HISTORY' -ForegroundColor Cyan
foreach ($g in $familyGroups) {
    Write-Host ('NH_HISTORY|item={0}|rows={1}|latestDoc={2}|latestCreated={3}|latestQty={4}|latestUom={5}|latestLocation={6}|latestPrice={7}|secondDoc={8}|secondCreated={9}|secondPrice={10}|quantities={11}|uoms={12}|locations={13}' -f
        $g.itemNumber,$g.rowCount,$g.latestDocument,$g.latestCreatedAt,$g.latestQuantity,$g.latestUom,$g.latestLocation,$g.latestPrice,
        $g.secondDocument,$g.secondCreatedAt,$g.secondPrice,($g.observedQuantities -join ','),($g.observedUoms -join ','),($g.observedLocations -join ','))
}
if ($familyGroups.Count -eq 0) { Write-Host 'NH_HISTORY|NONE' }

$familyRolling = @($rolling | Where-Object {
    $item = [string]$_.itemNumber
    -not [string]::IsNullOrWhiteSpace($item) -and $item.StartsWith($FamilyPrefix,[StringComparison]::OrdinalIgnoreCase)
} | Sort-Object lastSoldDate -Descending)

Write-Host ''
Write-Host 'NEW_GLARUS_3286_NH_ROLLING' -ForegroundColor Cyan
foreach ($r in $familyRolling) {
    Write-Host ('NH_ROLLING|item={0}|lastDate={1}|lastQty={2}|lastUom={3}|lastPrice={4}|location={5}' -f
        $r.itemNumber,$r.lastSoldDate,$r.lastSoldQuantity,$r.lastSoldUnitOfMeasureCode,$r.lastUnitPrice,$r.locationCode)
}
if ($familyRolling.Count -eq 0) { Write-Host 'NH_ROLLING|NONE' }

$familyItemNos = @(
    @($familyGroups | ForEach-Object {[string]$_.itemNumber}) +
    @($familyRolling | ForEach-Object {[string]$_.itemNumber})
) | Where-Object {-not [string]::IsNullOrWhiteSpace($_)} | Sort-Object -Unique
$familyItemNos = @($familyItemNos)

Write-Host ''
Write-Host 'NEW_GLARUS_3286_NH_CONFIGURED_UOM' -ForegroundColor Cyan
foreach ($itemNo in $familyItemNos) {
    $itemLit = Escape-ODataLiteral $itemNo
    $uomFilter = [Uri]::EscapeDataString("itemNumber eq '$itemLit'")
    $uoms = @(Invoke-BcGetAll "$customRoot/orderIntakeItemUnitsOfMeasure?`$filter=$uomFilter" $headers)
    foreach ($u in $uoms) {
        Write-Host ('NH_UOM|item={0}|code={1}|qtyPerUom={2}|rounding={3}' -f $itemNo,$u.code,$u.quantityPerUnitOfMeasure,$u.quantityRoundingPrecision)
    }
    if ($uoms.Count -eq 0) { Write-Host "NH_UOM|item=$itemNo|NONE" }
}

$locations = @(Invoke-BcGetAll "$companyRoot/locations?`$select=$locationSelect" $headers)
$canpackLocations = @($locations | Where-Object { $KnownLocationCodes -contains [string]$_.code })
Write-Host ''
Write-Host 'CANPACK_LOCATION_CONTEXT' -ForegroundColor Cyan
foreach ($l in $canpackLocations | Sort-Object code) {
    Write-Host ('CANPACK_LOCATION|code={0}|name={1}|city={2}|state={3}|sourceFacility={4}|mappingStatus=UNPROVEN' -f
        $l.code,$l.displayName,$l.city,$l.state,$SourceFacilityRef)
}

$exactSourceItem = '3286-NH01'
$exactHistory = @($familyGroups | Where-Object {[string]$_.itemNumber -eq $exactSourceItem})
$mostRecentFamily = @($familyGroups | Select-Object -First 1)

Write-Host ''
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'CANPACK SPOTTED COW FULL-HISTORY REV6 CONCLUSION' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "Vendor identity                 : $(if ($vendorRows.Count -eq 1) {'CANPUSA EXACT MATCH'} else {'REVIEW'})"
Write-Host "End-customer identity           : $(if ($customerRows.Count -eq 1) {'NEW EXACT MATCH'} else {'REVIEW'})"
Write-Host "Full posted history rows        : $($history.Count)"
Write-Host "3286-NH family contexts         : $($familyGroups.Count)"
Write-Host "Exact historical 3286-NH01     : $(if ($exactHistory.Count -gt 0) {'FOUND'} else {'NOT FOUND'})"
if ($mostRecentFamily.Count -eq 1) {
    Write-Host ('Most recent 3286-NH family item : {0} / {1} / {2} {3} / Location {4} / Price {5}' -f
        $mostRecentFamily[0].itemNumber,$mostRecentFamily[0].latestCreatedAt,$mostRecentFamily[0].latestQuantity,$mostRecentFamily[0].latestUom,$mostRecentFamily[0].latestLocation,$mostRecentFamily[0].latestPrice)
}
Write-Host 'Source TS -> BC UOM mapping      : UNPROVEN; numeric equivalence alone is insufficient'
Write-Host 'Source US50 -> BC Location       : UNPROVEN'
Write-Host 'Write authorization              : NOT GRANTED'
Write-Host 'Sales-order action               : NOT CALLED'
Write-Host 'Production                       : HARD BLOCKED'
Write-Host ('='*120) -ForegroundColor Cyan

[ordered]@{
    success=$true
    vendorNumber=$CanPackVendorNo
    vendorMatches=$vendorRows.Count
    customerNumber=$NewGlarusCustomerNo
    customerMatches=$customerRows.Count
    sourceMaterialReference=$SourceMaterialRef
    fullHistoryRows=$history.Count
    historyNewestCreated=$historyNewest
    historyOldestCreated=$historyOldest
    nhFamilyContexts=@($familyGroups)
    nhRolling=@($familyRolling)
    sourceFacilityReference=$SourceFacilityRef
    sourceUomMapping='UNPROVEN'
    locationMapping='UNPROVEN'
    writeAuthorization='NOT_GRANTED'
    safety=[ordered]@{
        httpMethods=@('GET')
        extensionMutation='NONE'
        businessDataWrites='NONE'
        salesOrderAction='NOT_CALLED'
        production='HARD_BLOCKED'
    }
} | ConvertTo-Json -Depth 20
