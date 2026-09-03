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
$CustomerNumber    = 'GIOVANN'
$ItemNumber        = 'C-503003-12033922'
$ObservedUom       = 'M'
$ObservedUnitPrice = [decimal]277.99

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
    if (-not (Get-Module -ListAvailable -Name Az.Accounts)) {
        throw 'Az.Accounts is required.'
    }
    Import-Module Az.Accounts -ErrorAction Stop

    try {
        $tokenResult = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
        $token = Convert-TokenToString $tokenResult.Token
        if (-not [string]::IsNullOrWhiteSpace($token)) { return $token }
    }
    catch {
    }

    Write-Host 'Starting Business Central scoped Microsoft sign-in...' -ForegroundColor Yellow
    Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null
    Connect-AzAccount -Tenant $TenantId -AuthScope 'https://api.businesscentral.dynamics.com' -Scope Process -ErrorAction Stop | Out-Null
    $tokenResult = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
    $token = Convert-TokenToString $tokenResult.Token
    if ([string]::IsNullOrWhiteSpace($token)) { throw 'Could not acquire Business Central access token.' }
    return $token
}

function Assert-BcUri {
    param([Parameter(Mandatory)][string]$Uri)
    $parsed = [Uri]$Uri
    if ($parsed.Scheme -ne 'https' -or $parsed.Host -ne 'api.businesscentral.dynamics.com') {
        throw "Unexpected Business Central URI blocked: $Uri"
    }
    if ($Uri.IndexOf($ForbiddenEnv, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Forbidden legacy sandbox URI blocked: $Uri"
    }
    if ($Uri.IndexOf('/Production/', [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Production-like URI blocked: $Uri"
    }
}

function Invoke-BcGet {
    param([Parameter(Mandatory)][string]$Uri, [Parameter(Mandatory)][hashtable]$Headers)
    Assert-BcUri $Uri
    Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 90
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    $Value.Replace("'", "''")
}

if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

$environmentResponse = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $headers
$environmentMatches = @($environmentResponse.value | Where-Object { [string]$_.name -eq $Environment })
if ($environmentMatches.Count -ne 1) { throw "Expected exactly one $Environment environment; found $($environmentMatches.Count)." }
$environmentType = [string]$environmentMatches[0].type
if ($environmentType -ine 'sandbox') { throw "SAFETY STOP: $Environment is type '$environmentType', not sandbox." }

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet -Uri "$standardRoot/companies" -Headers $headers
$companyMatches = @($companies.value | Where-Object {
    [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatches.Count -ne 1) { throw "Exact Gamer Packaging company verification failed; found $($companyMatches.Count)." }

$companyRoot = "$standardRoot/companies($CompanyId)"
$itemLiteral = Escape-ODataLiteral $ItemNumber
$itemFilter = [Uri]::EscapeDataString("number eq '$itemLiteral'")
$itemResponse = Invoke-BcGet -Uri "$companyRoot/items?`$filter=$itemFilter&`$top=2" -Headers $headers
$items = @($itemResponse.value)
if ($items.Count -ne 1) { throw "Expected exactly one item $ItemNumber; found $($items.Count)." }
$item = $items[0]

$itemUnitPrice = [decimal]$item.unitPrice
$thousandEquivalent = [decimal]($itemUnitPrice * 1000)
$matchesObservedPerM = [math]::Abs([double]($thousandEquivalent - $ObservedUnitPrice)) -lt 0.005

$result = [ordered]@{
    success = $true
    mode = 'GET_ONLY_ITEM_PRICE_BASIS'
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    customer = $CustomerNumber
    item = [ordered]@{
        id = $item.id
        number = $item.number
        displayName = $item.displayName
        type = $item.type
        blocked = $item.blocked
        baseUnitOfMeasureCode = $item.baseUnitOfMeasureCode
        unitPrice = $itemUnitPrice
        priceIncludesTax = $item.priceIncludesTax
        unitCost = $item.unitCost
    }
    observedSalesLine = [ordered]@{
        unitOfMeasureCode = $ObservedUom
        unitPrice = $ObservedUnitPrice
    }
    arithmeticCheckOnly = [ordered]@{
        itemUnitPriceTimes1000 = $thousandEquivalent
        equalsObservedMUnitPrice = $matchesObservedPerM
        note = 'This arithmetic check is not proof that M equals 1000 EA. Qty. per Unit of Measure still requires BC-authoritative confirmation.'
    }
    safety = [ordered]@{
        methodsUsed = 'GET ONLY'
        extensionMutation = 'NONE'
        salesOrderAction = 'NOT CALLED'
        businessDataWrites = 'NONE'
        production = 'HARD BLOCKED'
    }
}

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - ITEM PRICE BASIS / GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Item              : $ItemNumber"
Write-Host "Observed line     : $ObservedUnitPrice per $ObservedUom"
Write-Host 'Extension mutation: NONE' -ForegroundColor Green
Write-Host 'Sales-order action: NOT CALLED' -ForegroundColor Green
Write-Host 'Business data writes: NONE' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan
$result | ConvertTo-Json -Depth 20
Write-Host ''
Write-Host 'GPI ORDER INTAKE ITEM PRICE BASIS: GET-ONLY PASS' -ForegroundColor Green
