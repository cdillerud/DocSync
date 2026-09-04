#requires -Version 7.0

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$SearchText,

    [ValidateRange(1, 100)]
    [int]$Top = 25
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED ORDER-INTAKE READ-ONLY TARGET ONLY
# =====================================================================================================================
$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$ExpectedCompanyId = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'

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
        throw 'Az.Accounts is required. Install-Module Az.Accounts -Scope CurrentUser'
    }

    Import-Module Az.Accounts -ErrorAction Stop

    try {
        $tokenResult = Get-AzAccessToken `
            -TenantId $TenantId `
            -ResourceUrl 'https://api.businesscentral.dynamics.com' `
            -ErrorAction Stop

        $token = Convert-TokenToString $tokenResult.Token
        if (-not [string]::IsNullOrWhiteSpace($token)) { return $token }
    }
    catch {
        # Fall through to isolated interactive BC-scoped authentication.
    }

    Write-Host 'Starting Business Central scoped Microsoft sign-in...' -ForegroundColor Yellow
    Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null

    Connect-AzAccount `
        -Tenant $TenantId `
        -AuthScope 'https://api.businesscentral.dynamics.com' `
        -Scope Process `
        -ErrorAction Stop | Out-Null

    $tokenResult = Get-AzAccessToken `
        -TenantId $TenantId `
        -ResourceUrl 'https://api.businesscentral.dynamics.com' `
        -ErrorAction Stop

    $token = Convert-TokenToString $tokenResult.Token
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw 'Could not acquire Business Central access token.'
    }

    return $token
}

function Assert-CertifiedConfiguration {
    if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') {
        throw 'Tenant hard pin changed. Execution blocked.'
    }
    if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') {
        throw "Unauthorized Business Central environment '$Environment'. Execution blocked."
    }
    if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') {
        throw "Forbidden Business Central environment '$Environment'. Execution blocked."
    }
    if ($CompanyName -ne 'Gamer Packaging') {
        throw 'Company-name hard pin changed. Execution blocked.'
    }
    if ($ExpectedCompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') {
        throw 'Company-ID hard pin changed. Execution blocked.'
    }
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
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][hashtable]$Headers
    )

    Assert-BcUri -Uri $Uri
    return Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 90
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    return $Value.Replace("'", "''")
}

Assert-CertifiedConfiguration
$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

$environmentResponse = Invoke-BcGet `
    -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' `
    -Headers $headers

$environmentMatches = @(
    $environmentResponse.value |
    Where-Object { [string]$_.name -eq $Environment }
)

if ($environmentMatches.Count -ne 1) {
    throw "Expected exactly one $Environment environment; found $($environmentMatches.Count)."
}

$environmentType = [string]$environmentMatches[0].type
if ($environmentType -ine 'sandbox') {
    throw "SAFETY STOP: $Environment is type '$environmentType', not sandbox."
}

$environmentEncoded = [Uri]::EscapeDataString($Environment)
$apiRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$environmentEncoded/api/v2.0"
$companies = Invoke-BcGet -Uri "$apiRoot/companies" -Headers $headers
$companyMatches = @(
    $companies.value |
    Where-Object {
        [string]$_.id -eq $ExpectedCompanyId -and
        (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
    }
)

if ($companyMatches.Count -ne 1) {
    throw "Expected exact Gamer Packaging company ID $ExpectedCompanyId; found $($companyMatches.Count)."
}

$companyRoot = "$apiRoot/companies($ExpectedCompanyId)"
$literal = Escape-ODataLiteral $SearchText
$select = [Uri]::EscapeDataString('id,number,displayName,type,blocked,baseUnitOfMeasureCode')

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - GET-ONLY BC ITEM SEARCH' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment      : $Environment"
Write-Host "Environment type : $environmentType"
Write-Host "Company          : $CompanyName"
Write-Host "Company ID       : $ExpectedCompanyId"
Write-Host "Search text      : $SearchText"
Write-Host 'HTTP methods     : GET ONLY' -ForegroundColor Green
Write-Host 'Business writes  : NONE' -ForegroundColor Green
Write-Host 'Production       : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

$results = [System.Collections.Generic.List[object]]::new()
$seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

foreach ($filterExpression in @(
    "contains(number, '$literal')",
    "contains(displayName, '$literal')"
)) {
    $filter = [Uri]::EscapeDataString($filterExpression)
    $response = Invoke-BcGet `
        -Uri "$companyRoot/items?`$select=$select&`$filter=$filter&`$top=$Top" `
        -Headers $headers

    foreach ($item in @($response.value)) {
        if ($seen.Add([string]$item.id)) {
            $results.Add($item)
        }
    }
}

Write-Host "Matches found     : $($results.Count)"
Write-Host ''

[ordered]@{
    success = $true
    searchText = $SearchText
    environment = $Environment
    company = $CompanyName
    matchCount = $results.Count
    items = @($results | Sort-Object number)
    safety = [ordered]@{
        httpMethods = @('GET')
        businessCentralWrites = 'NONE'
        production = 'HARD BLOCKED'
    }
} | ConvertTo-Json -Depth 20
