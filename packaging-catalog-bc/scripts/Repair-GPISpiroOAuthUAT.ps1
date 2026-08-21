[CmdletBinding()]
param(
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml",
    [string]$ClientId = "",
    [string]$RedirectUri = "",
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$AuthorizeUrl = 'https://engine.spiro.ai/oauth/authorize'
$TokenUrl = 'https://engine.spiro.ai/oauth/token'
$ApiTestUrl = 'https://api.spiro.ai/api/v1/companies?page[number]=1&page[size]=1'

function Write-Section {
    param([Parameter(Mandatory)][string]$Text)
    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 72) -ForegroundColor Cyan
}

function Get-PropertyValue {
    param(
        [AllowNull()]$Object,
        [Parameter(Mandatory)][string[]]$Names
    )

    if ($null -eq $Object) { return $null }

    foreach ($name in $Names) {
        $property = $Object.PSObject.Properties |
            Where-Object { $_.Name -ieq $name } |
            Select-Object -First 1
        if ($property) { return $property.Value }
    }

    return $null
}

function Convert-SecretToText {
    param([AllowNull()]$Value)

    if ($null -eq $Value) { return $null }

    if ($Value -is [System.Security.SecureString]) {
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
        try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    }

    return [string]$Value
}

function Get-TokenContainer {
    param([Parameter(Mandatory)]$Root)

    $aliases = @('AccessToken','access_token','accessToken','Token')
    if ($null -ne (Get-PropertyValue -Object $Root -Names $aliases)) { return $Root }

    foreach ($name in @('Tokens','TokenData','OAuth','OAuthTokens','SpiroTokens')) {
        $candidate = Get-PropertyValue -Object $Root -Names @($name)
        if ($null -ne $candidate -and $null -ne (Get-PropertyValue -Object $candidate -Names $aliases)) {
            return $candidate
        }
    }

    return $Root
}

function Set-PropertyValue {
    param(
        [Parameter(Mandatory)]$Object,
        [Parameter(Mandatory)][string[]]$Aliases,
        [Parameter(Mandatory)][string]$PreferredName,
        [AllowNull()]$Value,
        [switch]$Secure
    )

    $property = $null
    foreach ($alias in $Aliases) {
        $property = $Object.PSObject.Properties |
            Where-Object { $_.Name -ieq $alias } |
            Select-Object -First 1
        if ($property) { break }
    }

    $storedValue = $Value
    if ($Secure -and $null -ne $Value) {
        $storedValue = ConvertTo-SecureString -String ([string]$Value) -AsPlainText -Force
    }

    if ($property) { $property.Value = $storedValue }
    else { $Object | Add-Member -NotePropertyName $PreferredName -NotePropertyValue $storedValue }
}

function Get-CodeFromInput {
    param([Parameter(Mandatory)][string]$InputText)

    $text = $InputText.Trim()
    if ([string]::IsNullOrWhiteSpace($text)) { return '' }

    if ($text -match '^[A-Za-z0-9._~-]+$' -and $text -notmatch '^https?://') {
        return $text
    }

    try {
        $uri = [uri]$text
        $query = [System.Web.HttpUtility]::ParseQueryString($uri.Query)
        return [string]$query['code']
    }
    catch {
        return ''
    }
}

Write-Section 'GPI SPIRO OAUTH UAT REAUTHORIZATION'

if (-not (Test-Path -LiteralPath $TokenStorePath)) {
    throw "Protected token store was not found: $TokenStorePath"
}

$root = Import-Clixml -LiteralPath $TokenStorePath
if ($null -eq $root) {
    throw "Protected token store could not be read: $TokenStorePath"
}

$container = Get-TokenContainer -Root $root

$resolvedClientId = $ClientId
if ([string]::IsNullOrWhiteSpace($resolvedClientId)) {
    $resolvedClientId = [string](Get-PropertyValue -Object $root -Names @('ClientId','client_id','SpiroClientId'))
}
if ([string]::IsNullOrWhiteSpace($resolvedClientId)) {
    $resolvedClientId = [string]$env:SPIRO_CLIENT_ID
}
if ([string]::IsNullOrWhiteSpace($resolvedClientId)) {
    $resolvedClientId = Read-Host 'Spiro OAuth client ID'
}
if ([string]::IsNullOrWhiteSpace($resolvedClientId)) {
    throw 'Spiro OAuth client ID is required.'
}

$resolvedRedirectUri = $RedirectUri
if ([string]::IsNullOrWhiteSpace($resolvedRedirectUri)) {
    $resolvedRedirectUri = [string](Get-PropertyValue -Object $root -Names @('RedirectUri','redirect_uri','SpiroRedirectUri'))
}
if ([string]::IsNullOrWhiteSpace($resolvedRedirectUri)) {
    $resolvedRedirectUri = [string]$env:SPIRO_REDIRECT_URI
}
if ([string]::IsNullOrWhiteSpace($resolvedRedirectUri)) {
    $resolvedRedirectUri = Read-Host 'Exact Spiro redirect URI configured for this OAuth authorization'
}
if ([string]::IsNullOrWhiteSpace($resolvedRedirectUri)) {
    throw 'The exact redirect URI is required. It must match the value configured in Spiro.'
}

$secretValue = Get-PropertyValue -Object $root -Names @('ClientSecret','client_secret','SpiroClientSecret')
$resolvedClientSecret = Convert-SecretToText -Value $secretValue
if ([string]::IsNullOrWhiteSpace($resolvedClientSecret)) {
    $resolvedClientSecret = [string]$env:SPIRO_CLIENT_SECRET
}
if ([string]::IsNullOrWhiteSpace($resolvedClientSecret)) {
    $secureSecret = Read-Host 'Spiro OAuth client secret' -AsSecureString
    $resolvedClientSecret = Convert-SecretToText -Value $secureSecret
}
if ([string]::IsNullOrWhiteSpace($resolvedClientSecret)) {
    throw 'Spiro OAuth client secret is required.'
}

Write-Host "Token store  : $TokenStorePath"
Write-Host "Client ID    : $resolvedClientId"
Write-Host "Redirect URI : $resolvedRedirectUri"
Write-Host 'Client secret: present, not displayed'

$authUri = $AuthorizeUrl +
    '?client_id=' + [uri]::EscapeDataString($resolvedClientId) +
    '&redirect_uri=' + [uri]::EscapeDataString($resolvedRedirectUri) +
    '&response_type=code'

Write-Section 'AUTHORIZE IN SPIRO'
Write-Host 'A browser window will open to Spiro authorization.'
Write-Host 'Authorize the application. When redirected, copy either:'
Write-Host '  1. the complete redirected URL, or'
Write-Host '  2. only the code query-string value.'
Write-Host ''

Start-Process $authUri

$redirectResult = Read-Host 'Paste the redirected URL or authorization code'
$authorizationCode = Get-CodeFromInput -InputText $redirectResult
if ([string]::IsNullOrWhiteSpace($authorizationCode)) {
    throw 'Could not extract an authorization code from the supplied value.'
}

Write-Section 'EXCHANGE AUTHORIZATION CODE'

try {
    $tokenResponse = Invoke-RestMethod `
        -Method POST `
        -Uri $TokenUrl `
        -ContentType 'application/json' `
        -Body (@{
            client_id = $resolvedClientId
            client_secret = $resolvedClientSecret
            code = $authorizationCode
            redirect_uri = $resolvedRedirectUri
            grant_type = 'authorization_code'
        } | ConvertTo-Json -Compress) `
        -TimeoutSec $TimeoutSeconds
}
finally {
    $resolvedClientSecret = $null
    $authorizationCode = $null
    $redirectResult = $null
}

$accessToken = [string]$tokenResponse.access_token
$refreshToken = [string]$tokenResponse.refresh_token
if ([string]::IsNullOrWhiteSpace($accessToken)) {
    throw 'Spiro did not return an access token.'
}
if ([string]::IsNullOrWhiteSpace($refreshToken)) {
    throw 'Spiro did not return a refresh token.'
}

$expiresIn = 3600
if ($tokenResponse.PSObject.Properties.Name -contains 'expires_in') {
    $expiresIn = [int]$tokenResponse.expires_in
}
$expiresAtUtc = [datetime]::UtcNow.AddSeconds($expiresIn)

$backupPath = $TokenStorePath + '.before-reauth-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
Copy-Item -LiteralPath $TokenStorePath -Destination $backupPath -Force

Set-PropertyValue -Object $container -Aliases @('AccessToken','access_token','accessToken','Token') -PreferredName 'AccessToken' -Value $accessToken -Secure
Set-PropertyValue -Object $container -Aliases @('RefreshToken','refresh_token','refreshToken') -PreferredName 'RefreshToken' -Value $refreshToken -Secure
Set-PropertyValue -Object $container -Aliases @('ExpiresAtUtc','expires_at','ExpiresAt','ExpirationUtc') -PreferredName 'ExpiresAtUtc' -Value $expiresAtUtc
Set-PropertyValue -Object $root -Aliases @('ClientId','client_id','SpiroClientId') -PreferredName 'ClientId' -Value $resolvedClientId
Set-PropertyValue -Object $root -Aliases @('RedirectUri','redirect_uri','SpiroRedirectUri') -PreferredName 'RedirectUri' -Value $resolvedRedirectUri

$root | Export-Clixml -LiteralPath $TokenStorePath -Force

Write-Host 'OAuth exchange succeeded.' -ForegroundColor Green
Write-Host "Protected token store updated: $TokenStorePath"
Write-Host "Backup created             : $backupPath"
Write-Host "Expires at UTC             : $($expiresAtUtc.ToString('u'))"

Write-Section 'SPIRO API VALIDATION'
$headers = @{
    Authorization = "Bearer $accessToken"
    Accept = 'application/json'
    'X-Api-Version' = '1'
}

$testResponse = Invoke-RestMethod `
    -Method GET `
    -Uri $ApiTestUrl `
    -Headers $headers `
    -TimeoutSec $TimeoutSeconds

$dataCount = 0
if ($testResponse.PSObject.Properties.Name -contains 'data') {
    $dataCount = @($testResponse.data).Count
}
elseif ($testResponse.PSObject.Properties.Name -contains 'companies') {
    $dataCount = @($testResponse.companies).Count
}
else {
    $dataCount = @($testResponse).Count
}

$accessToken = $null
$refreshToken = $null

Write-Host "Spiro API test records returned: $dataCount" -ForegroundColor Green
Write-Host 'SUCCESS: Spiro OAuth UAT authorization is valid again.' -ForegroundColor Green
Write-Host 'You can rerun Link-GPISpiroUATContext.ps1 in discovery mode.'
