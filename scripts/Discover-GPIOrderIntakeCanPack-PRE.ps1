#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# PRE-ONLY / GET-ONLY CANPACK DISCOVERY
#
# Current fixture clues are search evidence only, never universal rules:
#   candidate customer name : CanPack
#   product description     : SPOTTED COW
#   customer material ref   : 3286_NH01
#   source UOM              : TS
#   delivering plant        : US50
#
# The parser preserves each PO row's actual quantity/UOM/dates/plant. This script only discovers BC identities/mappings.
# It performs no extension mutation, no Sales Order action, and no business-data writes.
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

$CustomerClues = @('CANPACK','CAN PACK')
$ProductClues = @('SPOTTED COW')
$CustomerMaterialClues = @('3286_NH01','3286','NH01')
$SourceUom = 'TS'
$SourcePlant = 'US50'

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
        $next = [string]$r.'@odata.nextLink'
    }
    return @($rows)
}

function Escape-ODataLiteral { param([string]$Value) return $Value.Replace("'","''") }

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
Write-Host 'GPI ORDER INTAKE - CANPACK IDENTITY / ITEM / UOM / LOCATION DISCOVERY - PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "Environment        : $Environment"
Write-Host "Environment type   : $environmentType"
Write-Host "Company            : $CompanyName"
Write-Host "Installed app      : $ExpectedAppName $ExpectedVersion"
Write-Host 'Fixture clues      : SEARCH EVIDENCE ONLY - not universal PO rules'
Write-Host '  Customer         : CanPack'
Write-Host '  Product          : SPOTTED COW'
Write-Host '  Customer material: 3286_NH01'
Write-Host '  Source UOM       : TS'
Write-Host '  Delivering plant : US50'
Write-Host 'HTTP methods       : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation : NONE' -ForegroundColor Green
Write-Host 'Business data write: NONE' -ForegroundColor Green
Write-Host 'Sales-order action : NOT CALLED' -ForegroundColor Green
Write-Host 'Production         : HARD BLOCKED' -ForegroundColor Green
Write-Host ('='*120) -ForegroundColor Cyan

# Load standard customer/item/location masters completely, then match locally to avoid server-filter assumptions.
$customerSelect = [Uri]::EscapeDataString('id,number,displayName,addressLine1,addressLine2,city,state,country,postalCode,blocked')
$itemSelect = [Uri]::EscapeDataString('id,number,displayName,type,blocked,baseUnitOfMeasureCode')
$locationSelect = [Uri]::EscapeDataString('id,code,displayName,addressLine1,addressLine2,city,state,country,postalCode')
$customers = @(Invoke-BcGetAll "$companyRoot/customers?`$select=$customerSelect&`$top=200" $headers)
$items = @(Invoke-BcGetAll "$companyRoot/items?`$select=$itemSelect&`$top=200" $headers)
$locations = @(Invoke-BcGetAll "$companyRoot/locations?`$select=$locationSelect&`$top=200" $headers)

$customerCandidates = @($customers | Where-Object {
    $n = ([string]$_.displayName + ' ' + [string]$_.number).ToUpperInvariant()
    @($CustomerClues | Where-Object {$n.Contains($_)}).Count -gt 0
})

$itemClueCandidates = @($items | Where-Object {
    $text = ([string]$_.number + ' ' + [string]$_.displayName).ToUpperInvariant()
    $productHit = @($ProductClues | Where-Object {$text.Contains($_)}).Count -gt 0
    $materialHit = @($CustomerMaterialClues | Where-Object {$text.Contains($_)}).Count -gt 0
    $productHit -or $materialHit
})

$locationCandidates = @($locations | Where-Object {
    $text = ([string]$_.code + ' ' + [string]$_.displayName + ' ' + [string]$_.addressLine1 + ' ' + [string]$_.addressLine2 + ' ' + [string]$_.city + ' ' + [string]$_.state).ToUpperInvariant()
    $text.Contains($SourcePlant)
})

Write-Host ''
Write-Host 'CUSTOMER_CANDIDATES' -ForegroundColor Cyan
foreach ($c in $customerCandidates) {
    Write-Host ('CUSTOMER_CANDIDATE|number={0}|name={1}|city={2}|state={3}|blocked={4}' -f $c.number,$c.displayName,$c.city,$c.state,$c.blocked)
}
if ($customerCandidates.Count -eq 0) { Write-Host 'CUSTOMER_CANDIDATE|NONE' -ForegroundColor Yellow }

Write-Host ''
Write-Host 'DIRECT_ITEM_CLUE_CANDIDATES' -ForegroundColor Cyan
foreach ($i in $itemClueCandidates) {
    Write-Host ('ITEM_CLUE_CANDIDATE|item={0}|name={1}|baseUom={2}|blocked={3}' -f $i.number,$i.displayName,$i.baseUnitOfMeasureCode,$i.blocked)
}
if ($itemClueCandidates.Count -eq 0) { Write-Host 'ITEM_CLUE_CANDIDATE|NONE' -ForegroundColor Yellow }

Write-Host ''
Write-Host 'SOURCE_PLANT_LOCATION_CANDIDATES' -ForegroundColor Cyan
foreach ($l in $locationCandidates) {
    Write-Host ('LOCATION_CLUE_CANDIDATE|code={0}|name={1}|city={2}|state={3}' -f $l.code,$l.displayName,$l.city,$l.state)
}
if ($locationCandidates.Count -eq 0) { Write-Host 'LOCATION_CLUE_CANDIDATE|NONE' -ForegroundColor Yellow }

$historySummaries = [System.Collections.Generic.List[object]]::new()
$rollingSummaries = [System.Collections.Generic.List[object]]::new()
$uomEvidence = [System.Collections.Generic.List[object]]::new()

foreach ($c in $customerCandidates) {
    $customerNo = [string]$c.number
    $custLit = Escape-ODataLiteral $customerNo
    $filter = [Uri]::EscapeDataString("sellToCustomerNumber eq '$custLit'")
    $history = @(Invoke-BcGetAll "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$filter&`$top=200" $headers)
    $rolling = @(Invoke-BcGetAll "$customRoot/orderIntakeCustomerItemSales?`$filter=$filter&`$top=200" $headers)

    $itemIndex = @{}
    foreach ($item in $items) { $itemIndex[[string]$item.number] = $item }

    foreach ($g in @($history | Group-Object itemNumber)) {
        $itemNo = [string]$g.Name
        if ([string]::IsNullOrWhiteSpace($itemNo)) { continue }
        $rows = @($g.Group | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
        $detail = if ($itemIndex.ContainsKey($itemNo)) { $itemIndex[$itemNo] } else { $null }
        $name = if ($detail) { [string]$detail.displayName } else { '' }
        $search = ($itemNo + ' ' + $name).ToUpperInvariant()
        $descriptionHit = @($ProductClues | Where-Object {$search.Contains($_)}).Count -gt 0
        $materialHit = @($CustomerMaterialClues | Where-Object {$search.Contains($_)}).Count -gt 0
        $sourceUomHit = @($rows | Where-Object {[string]$_.unitOfMeasureCode -eq $SourceUom}).Count -gt 0

        $historySummaries.Add([pscustomobject][ordered]@{
            customerNumber=$customerNo
            customerName=[string]$c.displayName
            itemNumber=$itemNo
            itemName=$name
            rowCount=$rows.Count
            latestDocument=[string]$rows[0].documentNumber
            latestCreatedAt=[string]$rows[0].systemCreatedAt
            latestQuantity=[decimal]$rows[0].quantity
            latestUom=[string]$rows[0].unitOfMeasureCode
            latestLocation=[string]$rows[0].locationCode
            latestPrice=[decimal]$rows[0].unitPrice
            observedUoms=@($rows | ForEach-Object {[string]$_.unitOfMeasureCode} | Sort-Object -Unique)
            observedLocations=@($rows | ForEach-Object {[string]$_.locationCode} | Sort-Object -Unique)
            observedQuantities=@($rows | ForEach-Object {[decimal]$_.quantity} | Sort-Object -Unique)
            descriptionClueHit=$descriptionHit
            materialClueHit=$materialHit
            sourceUomHistoryHit=$sourceUomHit
        })
    }

    foreach ($r in $rolling) {
        $itemNo = [string]$r.itemNumber
        $detail = if ($itemIndex.ContainsKey($itemNo)) { $itemIndex[$itemNo] } else { $null }
        $rollingSummaries.Add([pscustomobject][ordered]@{
            customerNumber=$customerNo
            itemNumber=$itemNo
            itemName=if ($detail) {[string]$detail.displayName} else {''}
            lastSoldDate=[string]$r.lastSoldDate
            lastSoldQuantity=[decimal]$r.lastSoldQuantity
            lastSoldUom=[string]$r.lastSoldUnitOfMeasureCode
            lastUnitPrice=[decimal]$r.lastUnitPrice
            locationCode=[string]$r.locationCode
        })
    }
}

$interestingHistory = @($historySummaries | Where-Object {
    $_.descriptionClueHit -or $_.materialClueHit -or $_.sourceUomHistoryHit
} | Sort-Object customerNumber,itemNumber)

Write-Host ''
Write-Host 'CANPACK_HISTORY_EVIDENCE' -ForegroundColor Cyan
foreach ($h in $interestingHistory) {
    Write-Host ('HISTORY_CANDIDATE|customer={0}|item={1}|name={2}|rows={3}|latestQty={4}|latestUom={5}|latestLocation={6}|latestPrice={7}|uoms={8}|locations={9}|quantities={10}|productClue={11}|materialClue={12}|sourceUomHit={13}' -f
        $h.customerNumber,$h.itemNumber,$h.itemName,$h.rowCount,$h.latestQuantity,$h.latestUom,$h.latestLocation,$h.latestPrice,
        ($h.observedUoms -join ','),($h.observedLocations -join ','),($h.observedQuantities -join ','),$h.descriptionClueHit,$h.materialClueHit,$h.sourceUomHistoryHit)
}
if ($interestingHistory.Count -eq 0) { Write-Host 'HISTORY_CANDIDATE|NONE' -ForegroundColor Yellow }

# Pull configured Item UOMs for any directly/history-interesting item candidate.
$candidateItemNos = @(
    @($itemClueCandidates | ForEach-Object {[string]$_.number}) +
    @($interestingHistory | ForEach-Object {[string]$_.itemNumber})
) | Where-Object {-not [string]::IsNullOrWhiteSpace($_)} | Sort-Object -Unique

foreach ($itemNo in $candidateItemNos) {
    $itemLit = Escape-ODataLiteral $itemNo
    $filter = [Uri]::EscapeDataString("itemNumber eq '$itemLit'")
    $uoms = @(Invoke-BcGetAll "$customRoot/orderIntakeItemUnitsOfMeasure?`$filter=$filter&`$top=200" $headers)
    foreach ($u in $uoms) {
        $uomEvidence.Add([pscustomobject][ordered]@{
            itemNumber=$itemNo
            code=[string]$u.code
            quantityPerUnitOfMeasure=[decimal]$u.quantityPerUnitOfMeasure
            quantityRoundingPrecision=[decimal]$u.quantityRoundingPrecision
            matchesSourceUom=([string]$u.code -eq $SourceUom)
        })
    }
}

Write-Host ''
Write-Host 'CONFIGURED_UOM_EVIDENCE' -ForegroundColor Cyan
foreach ($u in $uomEvidence | Sort-Object itemNumber,code) {
    Write-Host ('UOM_EVIDENCE|item={0}|code={1}|qtyPerUom={2}|rounding={3}|matchesSourceUom={4}' -f $u.itemNumber,$u.code,$u.quantityPerUnitOfMeasure,$u.quantityRoundingPrecision,$u.matchesSourceUom)
}
if ($uomEvidence.Count -eq 0) { Write-Host 'UOM_EVIDENCE|NONE' -ForegroundColor Yellow }

Write-Host ''
Write-Host 'BOYER_ROLLING_EVIDENCE_FOR_INTERESTING_ITEMS' -ForegroundColor Cyan
foreach ($r in @($rollingSummaries | Where-Object {$candidateItemNos -contains $_.itemNumber} | Sort-Object customerNumber,itemNumber)) {
    Write-Host ('ROLLING_EVIDENCE|customer={0}|item={1}|name={2}|lastDate={3}|lastQty={4}|lastUom={5}|lastPrice={6}|location={7}' -f
        $r.customerNumber,$r.itemNumber,$r.itemName,$r.lastSoldDate,$r.lastSoldQuantity,$r.lastSoldUom,$r.lastUnitPrice,$r.locationCode)
}

$customerStatus = if ($customerCandidates.Count -eq 1) {'UNIQUE_NAME_CANDIDATE'} elseif ($customerCandidates.Count -eq 0) {'UNRESOLVED'} else {'AMBIGUOUS'}
$sourceUomConfiguredItems = @($uomEvidence | Where-Object {$_.matchesSourceUom} | Select-Object -ExpandProperty itemNumber -Unique)
$directMaterialMatch = @($itemClueCandidates | Where-Object {
    $text = ([string]$_.number + ' ' + [string]$_.displayName).ToUpperInvariant()
    $text.Contains('3286_NH01')
})

Write-Host ''
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'CANPACK DISCOVERY CONCLUSION' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "Sell-to identity status        : $customerStatus"
Write-Host "Customer candidates            : $($customerCandidates.Count)"
Write-Host "Direct item clue candidates    : $($itemClueCandidates.Count)"
Write-Host "History-interesting item groups: $($interestingHistory.Count)"
Write-Host "Items with configured TS UOM   : $($sourceUomConfiguredItems.Count)"
Write-Host "BC locations matching US50     : $($locationCandidates.Count)"
Write-Host 'Customer material 3286_NH01    : UNPROVEN unless an exact direct BC item/reference match appears above' -ForegroundColor Yellow
Write-Host 'Write authorization             : NOT GRANTED by this discovery run' -ForegroundColor Yellow
Write-Host 'Next decision                   : resolve exact customer-item reference and ship-to/location semantics before any CanPack Draft test'
Write-Host 'Production                      : HARD BLOCKED' -ForegroundColor Green
Write-Host ('='*120) -ForegroundColor Cyan

[ordered]@{
    success=$true
    customerStatus=$customerStatus
    customerCandidates=@($customerCandidates)
    itemClueCandidates=@($itemClueCandidates)
    interestingHistory=@($interestingHistory)
    configuredUomEvidence=@($uomEvidence)
    locationCandidates=@($locationCandidates)
    customerMaterialReference='3286_NH01'
    customerMaterialReferenceResolution=if ($directMaterialMatch.Count -gt 0) {'DIRECT_TEXT_MATCH_ONLY_REVIEW_REQUIRED'} else {'UNPROVEN'}
    writeAuthorization='NOT_GRANTED'
    safety=[ordered]@{
        httpMethods=@('GET')
        extensionMutation='NONE'
        businessDataWrites='NONE'
        salesOrderAction='NOT_CALLED'
        production='HARD_BLOCKED'
    }
} | ConvertTo-Json -Depth 30
