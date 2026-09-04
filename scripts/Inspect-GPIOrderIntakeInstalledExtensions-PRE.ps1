#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$TenantId     = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment  = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName  = 'Gamer Packaging'
$CompanyId    = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv = 'Sandbox_NoZetadocs_UAT'

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
$extensionsResponse = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$installed = @($extensionsResponse.value | Where-Object { $_.isInstalled -eq $true })

$normalized = @($installed | ForEach-Object {
    $version = '{0}.{1}.{2}.{3}' -f ([int]$_.versionMajor), ([int]$_.versionMinor), ([int]$_.versionBuild), ([int]$_.versionRevision)
    [ordered]@{
        id = [string]$_.id
        displayName = [string]$_.displayName
        publisher = [string]$_.publisher
        version = $version
        isInstalled = [bool]$_.isInstalled
    }
})

$nonMicrosoft = @($normalized | Where-Object {
    ([string]$_.publisher) -notmatch '^(?i)Microsoft( Corporation)?$'
} | Sort-Object publisher, displayName)

$gamerPublished = @($normalized | Where-Object {
    ([string]$_.publisher) -match '(?i)Gamer'
} | Sort-Object displayName)

$pricingNameHints = @($nonMicrosoft | Where-Object {
    (([string]$_.displayName) + ' ' + ([string]$_.publisher)) -match '(?i)price|pricing|sales|quote|catalog|gamer|gpi|cost|margin'
})

$result = [ordered]@{
    success = $true
    mode = 'GET_ONLY_PRE_EXTENSION_INVENTORY'
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    installedExtensionCount = @($normalized).Count
    nonMicrosoftInstalledExtensions = $nonMicrosoft
    gamerPublishedExtensions = $gamerPublished
    pricingNameHintExtensions = $pricingNameHints
    allInstalledExtensions = @($normalized | Sort-Object publisher, displayName)
    safety = [ordered]@{
        methodsUsed = 'GET ONLY'
        extensionMutation = 'NONE'
        salesOrderAction = 'NOT CALLED'
        businessDataWrites = 'NONE'
        production = 'HARD BLOCKED'
    }
}

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - PRE INSTALLED EXTENSION INVENTORY / GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Installed apps    : $(@($normalized).Count)"
Write-Host 'Extension mutation: NONE' -ForegroundColor Green
Write-Host 'Sales-order action: NOT CALLED' -ForegroundColor Green
Write-Host 'Business data writes: NONE' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan
$result | ConvertTo-Json -Depth 20
Write-Host ''
Write-Host 'GPI ORDER INTAKE PRE EXTENSION INVENTORY: GET-ONLY PASS' -ForegroundColor Green
