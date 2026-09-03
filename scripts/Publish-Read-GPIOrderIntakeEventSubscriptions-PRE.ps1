#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY EVENT-SUBSCRIPTION DIAGNOSTICS
# =====================================================================================================================
$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$CompanyId         = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'
$EnableFlag        = 'GPI_ORDER_INTAKE_EVENT_DIAGNOSTICS_ENABLED'

$ExpectedAppId       = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$ExpectedAppName     = 'GPI Order Intake'
$ExpectedPublisher   = 'Gamer Packaging Inc'
$ExpectedAppVersion  = '0.1.0.3'
$ExpectedPackageHash = 'AF33466161C0EF96C0303867B83599034F176BA2544F66D40C206D87B03FE878'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PackagePath = Join-Path $RepoRoot 'order-intake-bc\.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.3.app'

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

function Invoke-BcPost {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][hashtable]$Headers,
        [object]$Body
    )
    Assert-BcUri $Uri
    if ($null -eq $Body) {
        return Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -ContentType 'application/json' -TimeoutSec 90
    }
    Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -Body ($Body | ConvertTo-Json -Depth 20) -ContentType 'application/json' -TimeoutSec 90
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
        if ($page -gt $MaxPages) { throw "Pagination exceeded safety limit of $MaxPages pages." }
        $response = Invoke-BcGet -Uri $nextUri -Headers $Headers
        foreach ($row in @($response.value)) { $rows.Add($row) }
        $nextUri = [string]$response.'@odata.nextLink'
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
    if ($AppPublisherByName.ContainsKey($appName)) { $publisher = [string]$AppPublisherByName[$appName] }

    [ordered]@{
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

# ---------------------------------------------------------------------------------------------------------------------
# Fail-closed local preflight.
# ---------------------------------------------------------------------------------------------------------------------
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }
if ([Environment]::GetEnvironmentVariable($EnableFlag) -ine 'true') {
    throw "REFUSING PRE EVENT DIAGNOSTICS: set `$env:$EnableFlag = 'true' explicitly."
}
if (-not (Test-Path $PackagePath)) { throw "Compiled diagnostics package not found: $PackagePath" }
$actualHash = (Get-FileHash $PackagePath -Algorithm SHA256).Hash
if ($actualHash -ne $ExpectedPackageHash) {
    throw "Package SHA256 mismatch. Expected $ExpectedPackageHash; got $actualHash."
}

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

# Server-side environment/company verification before extension mutation.
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

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - PRE EVENT SUBSCRIPTION DIAGNOSTICS' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Company ID        : $CompanyId"
Write-Host "App               : $ExpectedAppName $ExpectedAppVersion"
Write-Host "App ID            : $ExpectedAppId"
Write-Host "Package SHA256    : $actualHash"
Write-Host 'Diagnostic table  : Event Subscription / READ ONLY'
Write-Host 'Sales-order action: NOT CALLED' -ForegroundColor Green
Write-Host 'Business data writes: NONE' -ForegroundColor Green
Write-Host 'Release/Ship/Post : NOT IMPLEMENTED / BLOCKED' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

# ---------------------------------------------------------------------------------------------------------------------
# Install/upgrade exact diagnostics version only if needed.
# ---------------------------------------------------------------------------------------------------------------------
$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$appMatches = @($extensions.value | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and
    [string]$_.displayName -eq $ExpectedAppName -and
    [string]$_.publisher -eq $ExpectedPublisher
})

$exactInstalled = @($appMatches | Where-Object {
    [int]$_.versionMajor -eq 0 -and [int]$_.versionMinor -eq 1 -and [int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 3 -and
    $_.isInstalled -eq $true
})
if ($exactInstalled.Count -gt 1) { throw 'More than one exact GPI Order Intake 0.1.0.3 installation was returned.' }

$deploymentPerformed = $false
if ($exactInstalled.Count -eq 1) {
    Write-Host 'GPI Order Intake 0.1.0.3 is already installed in PRE; skipping duplicate deployment.' -ForegroundColor Green
}
else {
    $conflictingIds = @($extensions.value | Where-Object {
        [string]$_.displayName -eq $ExpectedAppName -and [string]$_.publisher -eq $ExpectedPublisher -and [string]$_.id -ne $ExpectedAppId
    })
    if ($conflictingIds.Count -gt 0) { throw 'A GPI Order Intake app with an unexpected App ID exists. Stopping.' }

    Write-Host 'Creating PRE 0.1.0.3 extension-upload record...' -ForegroundColor Yellow
    $uploadRecord = Invoke-BcPost -Uri "$automationRoot/extensionUpload" -Headers $headers -Body ([ordered]@{
        schedule = 'Current version'
        schemaSyncMode = 'Add'
    })
    $uploadId = [string]$uploadRecord.systemId
    if ([string]::IsNullOrWhiteSpace($uploadId)) { throw 'extensionUpload did not return systemId.' }

    $contentUri = "$automationRoot/extensionUpload($uploadId)/extensionContent"
    Assert-BcUri $contentUri
    $binaryHeaders = @{ Authorization = "Bearer $token"; Accept = 'application/json'; 'If-Match' = '*' }
    Write-Host "Uploading vetted 0.1.0.3 package to PRE upload record $uploadId..." -ForegroundColor Yellow
    $patch = Invoke-WebRequest -Method Patch -Uri $contentUri -Headers $binaryHeaders -ContentType 'application/octet-stream' -InFile $PackagePath -SkipHttpErrorCheck -TimeoutSec 180
    if ([int]$patch.StatusCode -lt 200 -or [int]$patch.StatusCode -ge 300) {
        throw "Extension content upload failed: HTTP $($patch.StatusCode) $($patch.Content)"
    }

    $deploymentStart = [DateTimeOffset]::UtcNow.AddSeconds(-15)
    Write-Host 'Starting PRE 0.1.0.3 extension deployment...' -ForegroundColor Yellow
    $null = Invoke-BcPost -Uri "$automationRoot/extensionUpload($uploadId)/Microsoft.NAV.upload" -Headers $headers

    $completed = $false
    for ($attempt = 1; $attempt -le 90; $attempt++) {
        Start-Sleep -Seconds 2
        $statuses = Invoke-BcGet -Uri "$automationRoot/extensionDeploymentStatus?`$top=200" -Headers $headers
        $matches = @($statuses.value | Where-Object {
            [string]$_.name -eq $ExpectedAppName -and
            [string]$_.publisher -eq $ExpectedPublisher -and
            [string]$_.appVersion -eq $ExpectedAppVersion -and
            ([DateTimeOffset]$_.startedOn) -ge $deploymentStart
        } | Sort-Object { [DateTimeOffset]$_.startedOn } -Descending)

        if ($matches.Count -eq 0) { continue }
        $latest = $matches[0]
        Write-Host "Deployment status: $($latest.status)" -ForegroundColor Yellow
        if ([string]$latest.status -match '(?i)fail|error|cancel') {
            throw "GPI Order Intake 0.1.0.3 deployment failed with status '$($latest.status)'."
        }
        if ([string]$latest.status -match '(?i)complete|success') {
            $completed = $true
            $deploymentPerformed = $true
            break
        }
    }
    if (-not $completed) { throw 'Timed out waiting for GPI Order Intake 0.1.0.3 deployment.' }
}

# Verify exact version installed and refresh extension map.
$extensionsAfter = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$installed = @($extensionsAfter.value | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and
    [string]$_.displayName -eq $ExpectedAppName -and
    [string]$_.publisher -eq $ExpectedPublisher -and
    [int]$_.versionMajor -eq 0 -and [int]$_.versionMinor -eq 1 -and [int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 3 -and
    $_.isInstalled -eq $true
})
if ($installed.Count -ne 1) { throw "Expected exactly one installed $ExpectedAppName $ExpectedAppVersion; found $($installed.Count)." }
Write-Host 'PRE 0.1.0.3 extension verification: PASS' -ForegroundColor Green

# ---------------------------------------------------------------------------------------------------------------------
# GET-only Event Subscription diagnostics. No mutation below this point.
# ---------------------------------------------------------------------------------------------------------------------
$eventRows = $null
for ($attempt = 1; $attempt -le 45; $attempt++) {
    try {
        $eventRows = Get-AllBcPages -Uri "$customRoot/orderIntakeEventSubscriptions?`$top=1000" -Headers $headers
        break
    }
    catch {
        if ($attempt -eq 45) { throw }
        Start-Sleep -Seconds 2
    }
}
$eventRows = @($eventRows)

$appPublisherByName = @{}
foreach ($ext in @($extensionsAfter.value | Where-Object { $_.isInstalled -eq $true })) {
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
    if ($appPublisherByName.ContainsKey($appName)) { $publisher = [string]$appPublisherByName[$appName] }
    -not [string]::IsNullOrWhiteSpace($publisher) -and $publisher -ine 'Microsoft'
})

$highSignalRows = @($customRows | Where-Object {
    ([int]$_.publisherObjectId -in @(36, 37)) -or
    ((([string]$_.publishedFunction) + ' ' + ([string]$_.subscriberFunction)) -match $pricingHintRegex) -or
    ([string]$_.originatingAppName -match $candidateAppRegex)
})

function Convert-Rows {
    param([AllowEmptyCollection()][object[]]$Rows = @())
    @($Rows | Sort-Object originatingAppName, publisherObjectId, publishedFunction, subscriberCodeunitId, subscriberFunction | ForEach-Object {
        [pscustomobject](Convert-SubscriptionRow -Row $_ -AppPublisherByName $appPublisherByName)
    })
}

$installedCandidateExtensions = @($extensionsAfter.value | Where-Object {
    $_.isInstalled -eq $true -and [string]$_.displayName -match '(?i)(Boyer And Associates Custom Package|Gamer Spiro Integration)'
} | Select-Object id, displayName, publisher, versionMajor, versionMinor, versionBuild, versionRevision, isInstalled)

$result = [ordered]@{
    success = $true
    mode = 'PRE_EVENT_SUBSCRIPTION_DIAGNOSTICS'
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    installedApp = "$ExpectedAppName $ExpectedAppVersion"
    deploymentPerformed = $deploymentPerformed
    installedCandidateExtensions = $installedCandidateExtensions
    candidateAppSubscriptions = Convert-Rows -Rows $candidateAppRows
    salesHeaderLineSubscriptions = Convert-Rows -Rows $salesHeaderLineRows
    pricingNamedSubscriptions = Convert-Rows -Rows $pricingNamedRows
    highSignalCustomSubscriptions = Convert-Rows -Rows $highSignalRows
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
        packageHashVerified = $true
        extensionMutation = $(if ($deploymentPerformed) { 'GPI ORDER INTAKE DIAGNOSTICS UPGRADE ONLY' } else { 'NONE - ALREADY INSTALLED' })
        diagnosticMethodsAfterInstall = 'GET ONLY'
        salesOrderAction = 'NOT CALLED'
        businessDataWrites = 'NONE'
        releaseShipInvoicePost = 'NOT IMPLEMENTED / BLOCKED'
        production = 'HARD BLOCKED'
    }
}

$result | ConvertTo-Json -Depth 30
Write-Host ''
Write-Host 'GPI ORDER INTAKE EVENT SUBSCRIPTION DIAGNOSTICS: PASS' -ForegroundColor Green
