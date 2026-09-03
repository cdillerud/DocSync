#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# PRE-ONLY / GET-ONLY pricing-context profiler for installed GPI Order Intake 0.1.0.8.
# Pricing context = customer + item + UOM + location. Quantity is reported as evidence but is NOT part of the price key.
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
$GpiVersion     = '0.1.0.8'
$CustomerNumber = 'GIOVANN'

$Targets = @(
    [pscustomobject][ordered]@{ product='24oz Salsa';       itemNumber='C-503003-12033922'; role='NORMAL' },
    [pscustomobject][ordered]@{ product='16oz Vinegar';     itemNumber='C-8808-12026443';  role='NORMAL' },
    [pscustomobject][ordered]@{ product='14oz Pizza';       itemNumber='C-8479-10000229';  role='NORMAL' },
    [pscustomobject][ordered]@{ product='16oz Salsa';       itemNumber='C-503004-12033478'; role='NORMAL' },
    [pscustomobject][ordered]@{ product='24oz Pasta';       itemNumber='C-9874-10001833';  role='SOURCE_REVIEW' },
    [pscustomobject][ordered]@{ product='24oz Salsa mixed'; itemNumber='C-8682-12013925';  role='EXCEPTION_REVIEW' }
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
        [ValidateRange(1,50)][int]$MaxPages = 20
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

function Classify-PricingContext {
    param([Parameter(Mandatory)][AllowEmptyCollection()][object[]]$Rows)

    if ($Rows.Length -eq 0) {
        return [pscustomobject][ordered]@{
            decision='REVIEW_NO_HISTORY'; latestPrice=$null; secondLatestPrice=$null; latestDocument=$null; secondLatestDocument=$null
        }
    }

    $sorted = @($Rows | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
    $latest = $sorted[0]
    if ($sorted.Length -eq 1) {
        return [pscustomobject][ordered]@{
            decision='REVIEW_ONE_OBSERVATION'; latestPrice=[decimal]$latest.unitPrice; secondLatestPrice=$null;
            latestDocument=[string]$latest.documentNumber; secondLatestDocument=$null
        }
    }

    $second = $sorted[1]
    $p1 = [decimal]$latest.unitPrice
    $p2 = [decimal]$second.unitPrice
    $decision = if ($p1 -le 0 -or $p2 -le 0) {
        'REVIEW_NONPOSITIVE_PRICE'
    }
    elseif ($p1 -ne $p2) {
        'REVIEW_LATEST_TWO_DISAGREE'
    }
    else {
        'PASS_LATEST_TWO_AGREE'
    }

    return [pscustomobject][ordered]@{
        decision=$decision
        latestPrice=$p1
        secondLatestPrice=$p2
        latestDocument=[string]$latest.documentNumber
        secondLatestDocument=[string]$second.documentNumber
    }
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
$companyMatch = @($companies.value | Where-Object {
    [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatch.Length -ne 1) { throw 'Exact Gamer Packaging company verification failed.' }

$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"
$extensions = Invoke-BcGet "$automationRoot/extensions?`$top=500" $headers
$gpi = @($extensions.value | Where-Object {
    $_.isInstalled -eq $true -and [string]$_.id -eq $GpiAppId -and [string]$_.displayName -eq $GpiAppName -and
    [string]$_.publisher -eq $GpiPublisher -and (Get-InstalledVersionString $_) -eq $GpiVersion
})
if ($gpi.Length -ne 1) { throw "Expected exactly one installed $GpiAppName $GpiVersion; found $($gpi.Length)." }

Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE 0.1.0.8 - GIOVANNI PRICING-CONTEXT PROFILE / PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "Environment        : $Environment"
Write-Host "Environment type   : $environmentType"
Write-Host "Company            : $CompanyName"
Write-Host "Installed app      : $GpiAppName $GpiVersion"
Write-Host "Customer           : $CustomerNumber"
Write-Host 'Pricing key        : customer + item + UOM + location (quantity excluded)'
Write-Host 'HTTP methods       : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation : NONE' -ForegroundColor Green
Write-Host 'Business data write: NONE' -ForegroundColor Green
Write-Host 'Sales-order action : NOT CALLED' -ForegroundColor Green
Write-Host 'Production         : HARD BLOCKED' -ForegroundColor Green
Write-Host ('='*120) -ForegroundColor Cyan

$results = [System.Collections.Generic.List[object]]::new()

foreach ($target in $Targets) {
    $custLiteral = Escape-ODataLiteral $CustomerNumber
    $itemLiteral = Escape-ODataLiteral ([string]$target.itemNumber)
    $filter = [Uri]::EscapeDataString("sellToCustomerNumber eq '$custLiteral' and itemNumber eq '$itemLiteral'")
    $rows = @(Invoke-BcGetAll "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$filter&`$top=500" $headers)

    $groups = @($rows | Group-Object { ('{0}|{1}' -f [string]$_.unitOfMeasureCode, [string]$_.locationCode) })
    if ($groups.Length -eq 0) {
        $results.Add([pscustomobject][ordered]@{
            product=$target.product; itemNumber=$target.itemNumber; role=$target.role; uom=$null; locationCode=$null;
            rowCount=0; distinctQuantities=@(); decision='REVIEW_NO_HISTORY'; latestPrice=$null; secondLatestPrice=$null;
            latestDocument=$null; secondLatestDocument=$null
        })
        continue
    }

    foreach ($group in $groups) {
        $gRows = @($group.Group | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
        $classification = Classify-PricingContext $gRows
        $latest = $gRows[0]
        $quantities = @($gRows | ForEach-Object {[decimal]$_.quantity} | Sort-Object -Unique)

        $results.Add([pscustomobject][ordered]@{
            product=$target.product
            itemNumber=$target.itemNumber
            role=$target.role
            uom=[string]$latest.unitOfMeasureCode
            locationCode=[string]$latest.locationCode
            rowCount=$gRows.Length
            distinctQuantities=$quantities
            decision=$classification.decision
            latestPrice=$classification.latestPrice
            secondLatestPrice=$classification.secondLatestPrice
            latestDocument=$classification.latestDocument
            secondLatestDocument=$classification.secondLatestDocument
        })
    }
}

$ordered = @($results | Sort-Object product,uom,locationCode)
$ordered | Format-Table product,itemNumber,role,uom,locationCode,rowCount,decision,latestPrice,secondLatestPrice,latestDocument,secondLatestDocument -AutoSize | Out-Host

$review = @($ordered | Where-Object {[string]$_.decision -ne 'PASS_LATEST_TWO_AGREE'})
$agree = @($ordered | Where-Object {[string]$_.decision -eq 'PASS_LATEST_TWO_AGREE'})

Write-Host ''
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'PROFILE SUMMARY' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "Pricing contexts total       : $($ordered.Length)"
Write-Host "Latest-two agreement contexts: $($agree.Length)" -ForegroundColor Green
Write-Host "Review contexts              : $($review.Length)" -ForegroundColor Yellow

if ($review.Length -gt 0) {
    Write-Host ''
    Write-Host 'REAL FAIL-CLOSED PRICING-EVIDENCE CANDIDATES' -ForegroundColor Yellow
    $review | Format-Table product,itemNumber,role,uom,locationCode,rowCount,decision,latestPrice,secondLatestPrice,latestDocument,secondLatestDocument -AutoSize | Out-Host
}

Write-Host ''
Write-Host 'GPI ORDER INTAKE 0.1.0.8 PRICING-CONTEXT PROFILE: GET-ONLY PASS' -ForegroundColor Green
