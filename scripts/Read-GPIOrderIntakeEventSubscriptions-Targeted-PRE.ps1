#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY / GET-ONLY TARGETED EVENT-SUBSCRIPTION DIAGNOSTICS
# =====================================================================================================================
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
        # Fall through to isolated interactive BC-scoped authentication.
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
    return $Value.Replace("'", "''")
}

function Get-TargetedEventRows {
    param(
        [Parameter(Mandatory)][string]$CustomRoot,
        [Parameter(Mandatory)][hashtable]$Headers,
        [Parameter(Mandatory)][string]$Filter,
        [string]$Label = 'targeted event query'
    )

    $encodedFilter = [Uri]::EscapeDataString($Filter)
    $uri = "$CustomRoot/orderIntakeEventSubscriptions?`$filter=$encodedFilter&`$top=1000"
    $response = Invoke-BcGet -Uri $uri -Headers $Headers
    $rows = @($response.value)

    # A targeted query returning exactly 1000 rows would still be ambiguous because this API surface has already
    # demonstrated a 1000-row ceiling without a continuation link. Fail closed instead of silently truncating.
    if ($rows.Count -ge 1000) {
        throw "$Label returned $($rows.Count) rows and may be truncated by the 1000-row API ceiling. Narrow the filter further."
    }

    return $rows
}

function Get-RowKey {
    param([Parameter(Mandatory)]$Row)
    $id = [string]$Row.id
    if (-not [string]::IsNullOrWhiteSpace($id)) { return $id }

    return @(
        [string]$Row.originatingPackageId,
        [string]$Row.originatingAppName,
        [string]$Row.subscriberCodeunitId,
        [string]$Row.subscriberFunction,
        [string]$Row.publisherObjectType,
        [string]$Row.publisherObjectId,
        [string]$Row.publishedFunction
    ) -join '|'
}

function Convert-SubscriptionRow {
    param(
        [Parameter(Mandatory)]$Row,
        [Parameter(Mandatory)][hashtable]$AppPublisherByName
    )

    $appName = [string]$Row.originatingAppName
    $publisher = ''
    if ($AppPublisherByName.ContainsKey($appName)) {
        $publisher = [string]$AppPublisherByName[$appName]
    }

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
    param(
        [AllowEmptyCollection()][object[]]$Rows = @(),
        [Parameter(Mandatory)][hashtable]$AppPublisherByName
    )

    return @($Rows |
        Sort-Object originatingAppName, publisherObjectId, publishedFunction, subscriberCodeunitId, subscriberFunction |
        ForEach-Object { Convert-SubscriptionRow -Row $_ -AppPublisherByName $AppPublisherByName })
}

# ---------------------------------------------------------------------------------------------------------------------
# Fail-closed constants. This script contains GET only.
# ---------------------------------------------------------------------------------------------------------------------
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

# Server-side environment/company verification.
$environmentResponse = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $headers
$environmentMatches = @($environmentResponse.value | Where-Object { [string]$_.name -eq $Environment })
if ($environmentMatches.Count -ne 1) {
    throw "Expected exactly one $Environment environment; found $($environmentMatches.Count)."
}
$environmentType = [string]$environmentMatches[0].type
if ($environmentType -ine 'sandbox') {
    throw "SAFETY STOP: $Environment is type '$environmentType', not sandbox."
}

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet -Uri "$standardRoot/companies" -Headers $headers
$companyMatches = @($companies.value | Where-Object {
    [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatches.Count -ne 1) {
    throw "Exact Gamer Packaging company verification failed; found $($companyMatches.Count)."
}

$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"

# Verify exact diagnostics extension version. GET only.
$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$installedExtensions = @($extensions.value | Where-Object { $_.isInstalled -eq $true })
$installed = @($installedExtensions | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and
    [string]$_.displayName -eq $ExpectedAppName -and
    [string]$_.publisher -eq $ExpectedPublisher -and
    [int]$_.versionMajor -eq 0 -and
    [int]$_.versionMinor -eq 1 -and
    [int]$_.versionBuild -eq 0 -and
    [int]$_.versionRevision -eq 3
})
if ($installed.Count -ne 1) {
    throw "Expected exactly one installed $ExpectedAppName $ExpectedAppVersion; found $($installed.Count)."
}

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - TARGETED PRE EVENT SUBSCRIPTION DIAGNOSTICS / GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Company ID        : $CompanyId"
Write-Host "Installed app     : $ExpectedAppName $ExpectedAppVersion"
Write-Host 'Strategy          : SERVER-SIDE EXACT APP FILTERS + SALES HEADER/LINE FILTERS'
Write-Host 'Extension mutation: NONE' -ForegroundColor Green
Write-Host 'Diagnostic methods: GET ONLY' -ForegroundColor Green
Write-Host 'Sales-order action: NOT CALLED' -ForegroundColor Green
Write-Host 'Business data writes: NONE' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

$appPublisherByName = @{}
foreach ($ext in $installedExtensions) {
    $name = [string]$ext.displayName
    if (-not [string]::IsNullOrWhiteSpace($name)) {
        $appPublisherByName[$name] = [string]$ext.publisher
    }
}

$nonMicrosoftExtensions = @($installedExtensions | Where-Object {
    [string]$_.publisher -ine 'Microsoft'
} | Sort-Object publisher, displayName)

# Query each installed non-Microsoft app by exact originatingAppName. This bypasses the broad API's observed 1000-row ceiling.
$customRowsByKey = [ordered]@{}
$customAppSummary = [System.Collections.Generic.List[object]]::new()
$pricingHintRegex = '(?i)(price|pricing|unit.?price|discount|sales.?line|sales.?header|quantity|unit.?of.?measure|uom|location|validate)'

foreach ($ext in $nonMicrosoftExtensions) {
    $appName = [string]$ext.displayName
    if ([string]::IsNullOrWhiteSpace($appName)) { continue }

    $literal = Escape-ODataLiteral $appName
    $rows = @(Get-TargetedEventRows -CustomRoot $customRoot -Headers $headers -Filter "originatingAppName eq '$literal'" -Label "Event subscriptions for $appName")

    foreach ($row in $rows) {
        $customRowsByKey[(Get-RowKey -Row $row)] = $row
    }

    $activeRows = @($rows | Where-Object { $_.active -eq $true })
    $salesRows = @($activeRows | Where-Object { [int]$_.publisherObjectId -in @(36, 37) })
    $pricingRows = @($activeRows | Where-Object {
        (([string]$_.publishedFunction) + ' ' + ([string]$_.subscriberFunction)) -match $pricingHintRegex
    })

    $customAppSummary.Add([pscustomobject][ordered]@{
        displayName = $appName
        publisher = [string]$ext.publisher
        version = "$($ext.versionMajor).$($ext.versionMinor).$($ext.versionBuild).$($ext.versionRevision)"
        totalSubscriptions = $rows.Count
        activeSubscriptions = $activeRows.Count
        salesHeaderLineSubscriptions = $salesRows.Count
        pricingNamedSubscriptions = $pricingRows.Count
    })
}

$customRows = @($customRowsByKey.Values)
$activeCustomRows = @($customRows | Where-Object { $_.active -eq $true })
$customSalesHeaderLineRows = @($activeCustomRows | Where-Object { [int]$_.publisherObjectId -in @(36, 37) })
$customPricingRows = @($activeCustomRows | Where-Object {
    (([string]$_.publishedFunction) + ' ' + ([string]$_.subscriberFunction)) -match $pricingHintRegex
})
$highSignalCustomRows = @($activeCustomRows | Where-Object {
    ([int]$_.publisherObjectId -in @(36, 37)) -or
    ((([string]$_.publishedFunction) + ' ' + ([string]$_.subscriberFunction)) -match $pricingHintRegex)
})

$boyerRows = @($activeCustomRows | Where-Object { [string]$_.originatingAppName -eq 'Boyer And Associates Custom Package' })
$spiroRows = @($activeCustomRows | Where-Object { [string]$_.originatingAppName -eq 'Gamer Spiro Integration' })

# Independently query all Sales Header and Sales Line subscriptions using single-field filters. These result sets should be
# small and are not dependent on the broad 1000-row scan.
$salesHeaderRows = @(Get-TargetedEventRows -CustomRoot $customRoot -Headers $headers -Filter 'publisherObjectId eq 36' -Label 'Sales Header event subscriptions')
$salesLineRows = @(Get-TargetedEventRows -CustomRoot $customRoot -Headers $headers -Filter 'publisherObjectId eq 37' -Label 'Sales Line event subscriptions')

$result = [ordered]@{
    success = $true
    mode = 'GET_ONLY_TARGETED_PRE_EVENT_SUBSCRIPTION_DIAGNOSTICS'
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    installedApp = "$ExpectedAppName $ExpectedAppVersion"
    priorBroadScanLimitation = [ordered]@{
        observedRows = 1000
        observedNextLink = 'ABSENT'
        conclusion = 'Broad scan was capped/ambiguous and is not used to infer absence of custom subscribers.'
    }
    nonMicrosoftInstalledExtensions = @($nonMicrosoftExtensions | ForEach-Object {
        [pscustomobject][ordered]@{
            id = $_.id
            displayName = $_.displayName
            publisher = $_.publisher
            version = "$($_.versionMajor).$($_.versionMinor).$($_.versionBuild).$($_.versionRevision)"
        }
    })
    customAppSubscriptionSummary = @($customAppSummary)
    boyerCustomPackageSubscriptions = Convert-Rows -Rows $boyerRows -AppPublisherByName $appPublisherByName
    gamerSpiroSubscriptions = Convert-Rows -Rows $spiroRows -AppPublisherByName $appPublisherByName
    customSalesHeaderLineSubscriptions = Convert-Rows -Rows $customSalesHeaderLineRows -AppPublisherByName $appPublisherByName
    customPricingNamedSubscriptions = Convert-Rows -Rows $customPricingRows -AppPublisherByName $appPublisherByName
    highSignalCustomSubscriptions = Convert-Rows -Rows $highSignalCustomRows -AppPublisherByName $appPublisherByName
    allSalesHeaderSubscriptions = Convert-Rows -Rows $salesHeaderRows -AppPublisherByName $appPublisherByName
    allSalesLineSubscriptions = Convert-Rows -Rows $salesLineRows -AppPublisherByName $appPublisherByName
    counts = [ordered]@{
        nonMicrosoftInstalledExtensions = $nonMicrosoftExtensions.Count
        customSubscriptionsDiscoveredByExactAppQuery = $customRows.Count
        activeCustomSubscriptions = $activeCustomRows.Count
        boyerCustomPackageSubscriptions = $boyerRows.Count
        gamerSpiroSubscriptions = $spiroRows.Count
        customSalesHeaderLineSubscriptions = $customSalesHeaderLineRows.Count
        customPricingNamedSubscriptions = $customPricingRows.Count
        highSignalCustomSubscriptions = $highSignalCustomRows.Count
        allSalesHeaderSubscriptions = $salesHeaderRows.Count
        allSalesLineSubscriptions = $salesLineRows.Count
    }
    interpretationHints = @(
        'Exact originatingAppName filters bypass the ambiguous first-1000-row broad scan.',
        'A non-Microsoft app with zero rows from its exact-name query has no Event Subscription rows visible under that exact installed display name.',
        'Publisher object ID 36 is Sales Header and 37 is Sales Line.',
        'A custom app can still affect price without an EventSubscriber if it is called directly from a page/action/integration or if the price is supplied by an external process. Event Subscription absence is not proof of no influence.'
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
Write-Host 'GPI ORDER INTAKE TARGETED EVENT SUBSCRIPTION DIAGNOSTICS: GET-ONLY PASS' -ForegroundColor Green
