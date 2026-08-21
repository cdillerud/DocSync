[CmdletBinding()]
param(
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml",
    [string]$OpportunityId = '3463019',
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$SpiroApiBase = 'https://api.spiro.ai/api/v1'

function Get-PropertyValue {
    param(
        [AllowNull()]$Object,
        [Parameter(Mandatory)][string[]]$Names
    )

    if ($null -eq $Object) {
        return $null
    }

    foreach ($name in $Names) {
        $property = $Object.PSObject.Properties |
            Where-Object { $_.Name -ieq $name } |
            Select-Object -First 1

        if ($property) {
            return $property.Value
        }
    }

    return $null
}

function Convert-SecretValueToText {
    param([AllowNull()]$Value)

    if ($null -eq $Value) {
        return $null
    }

    if ($Value -is [System.Security.SecureString]) {
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
        try {
            return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
    }

    return [string]$Value
}

function Get-TokenContainer {
    param([Parameter(Mandatory)]$Root)

    $accessAliases = @('AccessToken', 'access_token', 'Token', 'accessToken')
    if ($null -ne (Get-PropertyValue -Object $Root -Names $accessAliases)) {
        return $Root
    }

    foreach ($containerName in @('Tokens', 'TokenData', 'OAuth', 'OAuthTokens', 'SpiroTokens')) {
        $candidate = Get-PropertyValue -Object $Root -Names @($containerName)
        if ($null -ne $candidate -and $null -ne (Get-PropertyValue -Object $candidate -Names $accessAliases)) {
            return $candidate
        }
    }

    return $Root
}

function Write-Section {
    param([Parameter(Mandatory)][string]$Text)

    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 72) -ForegroundColor Cyan
}

function Test-SensitivePropertyName {
    param([Parameter(Mandatory)][string]$Name)

    return $Name -match '(?i)token|secret|password|credential|api[_-]?key|authorization'
}

function Format-SafeValue {
    param(
        [Parameter(Mandatory)][string]$Name,
        [AllowNull()]$Value
    )

    if (Test-SensitivePropertyName -Name $Name) {
        return '<redacted>'
    }

    if ($null -eq $Value) {
        return '<null>'
    }

    if ($Value -is [string] -or $Value.GetType().IsPrimitive -or $Value -is [datetime]) {
        return [string]$Value
    }

    return ($Value | ConvertTo-Json -Depth 8 -Compress)
}

if (-not (Test-Path -LiteralPath $TokenStorePath)) {
    throw "Spiro protected token store was not found: $TokenStorePath"
}

$root = Import-Clixml -LiteralPath $TokenStorePath
if ($null -eq $root) {
    throw "Spiro token store could not be loaded: $TokenStorePath"
}

$container = Get-TokenContainer -Root $root
$accessValue = Get-PropertyValue -Object $container -Names @('AccessToken', 'access_token', 'accessToken', 'Token')
$accessToken = Convert-SecretValueToText -Value $accessValue

if ([string]::IsNullOrWhiteSpace($accessToken)) {
    throw 'No Spiro access token was found in the protected token store.'
}

Write-Section 'GPI SPIRO OPPORTUNITY UAT INSPECTOR'
Write-Host "Token store     : $TokenStorePath"
Write-Host "Opportunity ID  : $OpportunityId"
Write-Host 'Business Central: no calls or writes' -ForegroundColor Green
Write-Host 'Spiro           : GET only' -ForegroundColor Green

$headers = @{
    Authorization = "Bearer $accessToken"
    Accept = 'application/json'
    'X-Api-Version' = '1'
}

$response = Invoke-RestMethod `
    -Method GET `
    -Uri "$SpiroApiBase/opportunities/$OpportunityId" `
    -Headers $headers `
    -TimeoutSec $TimeoutSeconds

$record = $response
if ($response.PSObject.Properties.Name -contains 'data') {
    $record = $response.data
}

if ($null -eq $record) {
    throw "Spiro opportunity $OpportunityId returned no record."
}

Write-Section 'TOP LEVEL'
Write-Host "ID   : $([string](Get-PropertyValue -Object $record -Names @('id','Id')))"
Write-Host "Type : $([string](Get-PropertyValue -Object $record -Names @('type','Type')))"
Write-Host "Fields: $($record.PSObject.Properties.Name -join ', ')"

$attributes = Get-PropertyValue -Object $record -Names @('attributes')
Write-Section 'ATTRIBUTES'
if ($null -eq $attributes) {
    Write-Host '<none>'
}
else {
    foreach ($property in $attributes.PSObject.Properties | Sort-Object Name) {
        Write-Host ("{0} = {1}" -f $property.Name, (Format-SafeValue -Name $property.Name -Value $property.Value))
    }
}

$relationships = Get-PropertyValue -Object $record -Names @('relationships')
Write-Section 'RELATIONSHIPS'
if ($null -eq $relationships) {
    Write-Host '<none>'
}
else {
    foreach ($property in $relationships.PSObject.Properties | Sort-Object Name) {
        Write-Host ("{0} = {1}" -f $property.Name, (Format-SafeValue -Name $property.Name -Value $property.Value))
    }
}

$links = Get-PropertyValue -Object $record -Names @('links')
Write-Section 'LINKS'
if ($null -eq $links) {
    Write-Host '<none>'
}
else {
    foreach ($property in $links.PSObject.Properties | Sort-Object Name) {
        Write-Host ("{0} = {1}" -f $property.Name, (Format-SafeValue -Name $property.Name -Value $property.Value))
    }
}

Write-Section 'CANDIDATE CRM FIELDS'
foreach ($name in @(
    'name',
    'stage',
    'stage_name',
    'status',
    'owner',
    'owner_name',
    'assigned_to_name',
    'sales_rep_name',
    'web_url',
    'browser_url',
    'app_url',
    'contact_id',
    'company_id'
)) {
    $value = $null
    if ($null -ne $attributes) {
        $value = Get-PropertyValue -Object $attributes -Names @($name)
    }
    Write-Host ("{0} = {1}" -f $name, (Format-SafeValue -Name $name -Value $value))
}

$accessToken = $null
Write-Host ''
Write-Host 'Inspection complete.' -ForegroundColor Green
