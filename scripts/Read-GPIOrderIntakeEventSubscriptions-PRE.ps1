#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY / GET-ONLY EVENT-SUBSCRIPTION DIAGNOSTICS
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

function Get-AllBcPages {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][hashtable]$Headers,
        [int]$MaxPages = 50
    )

    $rows = [System.Collections.Generic.List[object]]::new()
    $nextUri = $Uri
    $page = 0

    while (-not [string]::IsNullOrWhiteSpace($nextUri)) {
        $page++
        if ($page -gt $MaxPages) {
            throw "Pagination exceeded safety limit of $MaxPages pages."
        }

        $response = Invoke-BcGet -Uri $nextUri -Headers $Headers
        foreach ($row in @($response.value)) {
            $rows.Add($row)
        }

        # Under Set-StrictMode, the final OData page often omits @odata.nextLink entirely.
        # Treat a missing property as the normal end-of-pagination condition.
        if ($response.PSObject.Properties.Name -contains '@odata.nextLink') {
            $nextUri = [string]$response.'@odata.nextLink'
        }
        else {
            $nextUri = $null
        }
    }

    return @($rows)
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
Write-Host 'GPI ORDER INTAKE - PRE EVENT SUBSCRIPTION DIAGNOSTICS RESUME / GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Company ID        : $CompanyId"
Write-Host "Installed app     : $ExpectedAppName $ExpectedAppVersion"
Write-Host 'Extension mutation: NONE' -ForegroundColor Green
Write-Host 'Diagnostic methods: GET ONLY' -ForegroundColor Green
Write-Host 'Sales-order action: NOT CALLED' -ForegroundColor Green
Write-Host 'Business data writes: NONE' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

# GET-only Event Subscription reads.
$eventRows = Get-AllBcPages -Uri "$customRoot/orderIntakeEventSubscriptions?`$top=1000" -Headers $headers
$eventRows = @($eventRows)

$appPublisherByName = @{}
foreach ($ext in $installedExtensions) {
    $name = [string]$ext.displayName
    if (-not [string]::IsNullOrWhiteSpace($name)) {
        $appPublisherByName[$name] = [string]$ext.publisher
    }
}

$activeRows = @($eventRows | Where-Object { $_.active -eq $true })
$candidateAppRegex = '(?i)(Boyer And Associates Custom Package|Gamer Spiro Integration|Gamer Packaging|GPI |Zetadocs)'
$pricingHintRegex = '(?i)(price|pricing|unit.?price|discount|sales.?line|sales.?header|quantity|unit.?of.?measure|uom|location|validate)'

$candidateAppRows = @($activeRows | Where-Object {
    [string]$_.originatingAppName -match $candidateAppRegex
})

$salesHeaderLineRows = @($activeRows | Where-Object {
    [int]$_.publisherObjectId -in @(36, 37)
})

$pricingNamedRows = @($activeRows | Where-Object {
    (([string]$_.publishedFunction) + ' ' + ([string]$_.subscriberFunction)) -match $pricingHintRegex
})

$customRows = @($activeRows | Where-Object {
    $appName = [string]$_.originatingAppName
    if ([string]::IsNullOrWhiteSpace($appName)) { return $false }

    $publisher = ''
    if ($appPublisherByName.ContainsKey($appName)) {
        $publisher = [string]$appPublisherByName[$appName]
    }

    -not [string]::IsNullOrWhiteSpace($publisher) -and $publisher -ine 'Microsoft'
})

$highSignalRows = @($customRows | Where-Object {
    ([int]$_.publisherObjectId -in @(36, 37)) -or
    ((([string]$_.publishedFunction) + ' ' + ([string]$_.subscriberFunction)) -match $pricingHintRegex) -or
    ([string]$_.originatingAppName -match $candidateAppRegex)
})

$installedCandidateExtensions = @($installedExtensions | Where-Object {
    [string]$_.displayName -match '(?i)(Boyer And Associates Custom Package|Gamer Spiro Integration)'
} | ForEach-Object {
    [pscustomobject][ordered]@{
        id = $_.id
        displayName = $_.displayName
        publisher = $_.publisher
        version = "$($_.versionMajor).$($_.versionMinor).$($_.versionBuild).$($_.versionRevision)"
        isInstalled = $_.isInstalled
    }
})

$result = [ordered]@{
    success = $true
    mode = 'GET_ONLY_PRE_EVENT_SUBSCRIPTION_DIAGNOSTICS'
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    installedApp = "$ExpectedAppName $ExpectedAppVersion"
    installedCandidateExtensions = $installedCandidateExtensions
    candidateAppSubscriptions = Convert-Rows -Rows $candidateAppRows -AppPublisherByName $appPublisherByName
    salesHeaderLineSubscriptions = Convert-Rows -Rows $salesHeaderLineRows -AppPublisherByName $appPublisherByName
    pricingNamedSubscriptions = Convert-Rows -Rows $pricingNamedRows -AppPublisherByName $appPublisherByName
    highSignalCustomSubscriptions = Convert-Rows -Rows $highSignalRows -AppPublisherByName $appPublisherByName
    counts = [ordered]@{
        allEventSubscriptions = @($eventRows).Count
        activeEventSubscriptions = @($activeRows).Count
        activeCustomAppSubscriptions = @($customRows).Count
        candidateAppSubscriptions = @($candidateAppRows).Count
        salesHeaderLineSubscriptions = @($salesHeaderLineRows).Count
        pricingNamedSubscriptions = @($pricingNamedRows).Count
        highSignalCustomSubscriptions = @($highSignalRows).Count
    }
    interpretationHints = @(
        'Publisher object ID 37 is Sales Line; 36 is Sales Header.',
        'A candidate app appearing only in installedCandidateExtensions but not candidateAppSubscriptions has no active event subscribers visible in this table.',
        'High-signal rows are selected locally by custom publisher plus Sales Header/Line object or pricing/order-related function names. They are diagnostic evidence, not proof of causation.'
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
Write-Host 'GPI ORDER INTAKE EVENT SUBSCRIPTION DIAGNOSTICS: GET-ONLY PASS' -ForegroundColor Green
