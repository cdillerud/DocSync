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
$ExpectedAppVersion = '0.1.0.3'

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
        $tokenResult = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
        $token = Convert-TokenToString $tokenResult.Token
        if (-not [string]::IsNullOrWhiteSpace($token)) { return $token }
    }
    catch { }

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
    return $Value.Replace("'", "''")
}

function Get-AppEvents {
    param(
        [Parameter(Mandatory)][string]$CustomRoot,
        [Parameter(Mandatory)][hashtable]$Headers,
        [Parameter(Mandatory)][string]$AppName
    )
    $literal = Escape-ODataLiteral $AppName
    $filter = [Uri]::EscapeDataString("originatingAppName eq '$literal'")
    $uri = "$CustomRoot/orderIntakeEventSubscriptions?`$filter=$filter&`$top=1000"
    $response = Invoke-BcGet -Uri $uri -Headers $Headers
    $rows = @($response.value)
    if ($rows.Count -ge 1000) { throw "Exact app query for $AppName returned 1000 rows and may be truncated." }
    return $rows
}

function Convert-Row {
    param([Parameter(Mandatory)]$Row, [Parameter(Mandatory)][hashtable]$AppPublisherByName)
    $appName = [string]$Row.originatingAppName
    $publisher = ''
    if ($AppPublisherByName.ContainsKey($appName)) { $publisher = [string]$AppPublisherByName[$appName] }
    [pscustomobject][ordered]@{
        originatingAppName = $appName
        originatingAppPublisher = $publisher
        active = [bool]$Row.active
        subscriberCodeunitId = $Row.subscriberCodeunitId
        subscriberFunction = $Row.subscriberFunction
        publisherObjectType = $Row.publisherObjectType
        publisherObjectId = $Row.publisherObjectId
        publishedFunction = $Row.publishedFunction
        eventType = $Row.eventType
        numberOfCalls = $Row.numberOfCalls
        subscriberInstance = $Row.subscriberInstance
        activeManualInstances = $Row.activeManualInstances
        errorInformation = $Row.errorInformation
        originatingPackageId = $Row.originatingPackageId
    }
}

function Convert-Rows {
    param([AllowEmptyCollection()][object[]]$Rows = @(), [Parameter(Mandatory)][hashtable]$AppPublisherByName)
    $out = [System.Collections.Generic.List[object]]::new()
    foreach ($row in @($Rows | Sort-Object publisherObjectType, publisherObjectId, publishedFunction, subscriberCodeunitId, subscriberFunction)) {
        $out.Add((Convert-Row -Row $row -AppPublisherByName $AppPublisherByName))
    }
    return @($out.ToArray())
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

$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"

$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$installedExtensions = @($extensions.value | Where-Object { $_.isInstalled -eq $true })
$installed = @($installedExtensions | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and
    [string]$_.displayName -eq $ExpectedAppName -and
    [string]$_.publisher -eq $ExpectedPublisher -and
    [int]$_.versionMajor -eq 0 -and [int]$_.versionMinor -eq 1 -and [int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 3
})
if ($installed.Count -ne 1) { throw "Expected exactly one installed $ExpectedAppName $ExpectedAppVersion; found $($installed.Count)." }

$appPublisherByName = @{}
foreach ($ext in $installedExtensions) {
    $name = [string]$ext.displayName
    if (-not [string]::IsNullOrWhiteSpace($name)) { $appPublisherByName[$name] = [string]$ext.publisher }
}

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - BOYER / SPIRO / PACKAGING EVENT DETAILS / GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Installed app     : $ExpectedAppName $ExpectedAppVersion"
Write-Host 'Extension mutation: NONE' -ForegroundColor Green
Write-Host 'Diagnostic methods: GET ONLY' -ForegroundColor Green
Write-Host 'Sales-order action: NOT CALLED' -ForegroundColor Green
Write-Host 'Business data writes: NONE' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

$boyerRows = @(Get-AppEvents -CustomRoot $customRoot -Headers $headers -AppName 'Boyer And Associates Custom Package')
$spiroRows = @(Get-AppEvents -CustomRoot $customRoot -Headers $headers -AppName 'Gamer Spiro Integration')
$packagingRows = @(Get-AppEvents -CustomRoot $customRoot -Headers $headers -AppName 'GPI Packaging Catalog')

$strictPricingRegex = '(?i)(price|pricing|discount)'
$contextRegex = '(?i)(item|quantity|unit.?of.?measure|uom|location|ship.?to|shipment|customer|sell.?to|bill.?to)'

$boyerStrictPricing = @($boyerRows | Where-Object {
    (([string]$_.subscriberFunction) + ' ' + ([string]$_.publishedFunction)) -match $strictPricingRegex
})
$boyerSalesHeaderLine = @($boyerRows | Where-Object { [int]$_.publisherObjectId -in @(36, 37) })
$boyerContext = @($boyerRows | Where-Object {
    (([string]$_.subscriberFunction) + ' ' + ([string]$_.publishedFunction)) -match $contextRegex
})
$spiroSalesHeaderLine = @($spiroRows | Where-Object { [int]$_.publisherObjectId -in @(36, 37) })
$packagingSalesHeaderLine = @($packagingRows | Where-Object { [int]$_.publisherObjectId -in @(36, 37) })
$packagingStrictPricing = @($packagingRows | Where-Object {
    (([string]$_.subscriberFunction) + ' ' + ([string]$_.publishedFunction)) -match $strictPricingRegex
})

$result = [ordered]@{
    success = $true
    mode = 'GET_ONLY_BOYER_SPIRO_PACKAGING_EVENT_DETAILS'
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    installedApp = "$ExpectedAppName $ExpectedAppVersion"
    boyerStrictPricingSubscriptions = Convert-Rows -Rows $boyerStrictPricing -AppPublisherByName $appPublisherByName
    boyerSalesHeaderLineSubscriptions = Convert-Rows -Rows $boyerSalesHeaderLine -AppPublisherByName $appPublisherByName
    boyerOrderContextSubscriptions = Convert-Rows -Rows $boyerContext -AppPublisherByName $appPublisherByName
    allBoyerSubscriptions = Convert-Rows -Rows $boyerRows -AppPublisherByName $appPublisherByName
    spiroSalesHeaderLineSubscriptions = Convert-Rows -Rows $spiroSalesHeaderLine -AppPublisherByName $appPublisherByName
    allSpiroSubscriptions = Convert-Rows -Rows $spiroRows -AppPublisherByName $appPublisherByName
    packagingCatalogSalesHeaderLineSubscriptions = Convert-Rows -Rows $packagingSalesHeaderLine -AppPublisherByName $appPublisherByName
    packagingCatalogStrictPricingSubscriptions = Convert-Rows -Rows $packagingStrictPricing -AppPublisherByName $appPublisherByName
    allPackagingCatalogSubscriptions = Convert-Rows -Rows $packagingRows -AppPublisherByName $appPublisherByName
    counts = [ordered]@{
        boyerAll = $boyerRows.Count
        boyerStrictPricing = $boyerStrictPricing.Count
        boyerSalesHeaderLine = $boyerSalesHeaderLine.Count
        boyerOrderContext = $boyerContext.Count
        spiroAll = $spiroRows.Count
        spiroSalesHeaderLine = $spiroSalesHeaderLine.Count
        packagingCatalogAll = $packagingRows.Count
        packagingCatalogSalesHeaderLine = $packagingSalesHeaderLine.Count
        packagingCatalogStrictPricing = $packagingStrictPricing.Count
    }
    interpretationHints = @(
        'Strict pricing means event/subscriber names containing price, pricing, or discount only; generic validate/sales-line names are not counted as pricing.',
        'An app can still change Unit Price inside a generically named subscriber, so zero strict-price names is not proof of no price influence.',
        'Sales Header publisher object ID is 36; Sales Line is 37.'
    )
    safety = [ordered]@{
        extensionMutation = 'NONE'
        diagnosticMethods = 'GET ONLY'
        salesOrderAction = 'NOT CALLED'
        businessDataWrites = 'NONE'
        releaseShipInvoicePost = 'NOT IMPLEMENTED / BLOCKED'
        production = 'HARD BLOCKED'
    }
}

$result | ConvertTo-Json -Depth 30
Write-Host ''
Write-Host 'GPI ORDER INTAKE BOYER EVENT DETAIL DIAGNOSTICS: GET-ONLY PASS' -ForegroundColor Green
