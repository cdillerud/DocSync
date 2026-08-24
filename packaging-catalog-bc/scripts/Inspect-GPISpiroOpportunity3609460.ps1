[CmdletBinding()]
param(
    [string]$OpportunityId = '3609460',
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml",
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

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

function Convert-SecretValueToText {
    param([AllowNull()]$Value)

    if ($null -eq $Value) { return $null }

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

function Write-Value {
    param(
        [Parameter(Mandatory)][string]$Path,
        [AllowNull()]$Value
    )

    if ($null -eq $Value) {
        Write-Host ("{0,-55} <null>" -f $Path)
        return
    }

    if ($Value -is [string] -or $Value.GetType().IsPrimitive -or $Value -is [decimal] -or $Value -is [datetime]) {
        Write-Host ("{0,-55} {1}" -f $Path, ([string]$Value))
        return
    }

    if ($Value -is [System.Collections.IDictionary]) {
        foreach ($key in $Value.Keys) {
            Write-Value -Path "$Path.$key" -Value $Value[$key]
        }
        return
    }

    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        $index = 0
        foreach ($item in $Value) {
            Write-Value -Path "$Path[$index]" -Value $item
            $index++
        }
        if ($index -eq 0) {
            Write-Host ("{0,-55} []" -f $Path)
        }
        return
    }

    $properties = @($Value.PSObject.Properties)
    if ($properties.Count -eq 0) {
        Write-Host ("{0,-55} {1}" -f $Path, ([string]$Value))
        return
    }

    foreach ($property in $properties) {
        Write-Value -Path "$Path.$($property.Name)" -Value $property.Value
    }
}

if (-not (Test-Path -LiteralPath $TokenStorePath)) {
    throw "Spiro token store not found: $TokenStorePath"
}

$root = Import-Clixml -LiteralPath $TokenStorePath
$container = Get-TokenContainer -Root $root
$accessToken = Convert-SecretValueToText -Value (Get-PropertyValue -Object $container -Names @('AccessToken', 'access_token', 'accessToken', 'Token'))

if ([string]::IsNullOrWhiteSpace($accessToken)) {
    throw 'No Spiro access token was found in the protected token store.'
}

$uri = "https://api.spiro.ai/api/v1/opportunities/${OpportunityId}?include=user"
Write-Host ''
Write-Host '========================================================================' -ForegroundColor Cyan
Write-Host "SPIRO OPPORTUNITY RAW FIELD INSPECTION [$OpportunityId]" -ForegroundColor Cyan
Write-Host '========================================================================' -ForegroundColor Cyan
Write-Host 'Read-only request. No Business Central or Spiro writes will be performed.' -ForegroundColor Green
Write-Host "URI: $uri" -ForegroundColor DarkGray

$response = Invoke-RestMethod `
    -Method GET `
    -Uri $uri `
    -Headers @{
        Authorization = "Bearer $accessToken"
        Accept = 'application/json'
        'X-Api-Version' = '1'
    } `
    -TimeoutSec $TimeoutSeconds

$data = Get-PropertyValue -Object $response -Names @('data')
if ($data -is [System.Array]) {
    $data = @($data) | Select-Object -First 1
}
if ($null -eq $data) {
    $data = $response
}

Write-Host ''
Write-Host '--- TOP-LEVEL DATA FIELDS ---' -ForegroundColor Yellow
foreach ($property in @($data.PSObject.Properties | Sort-Object Name)) {
    if ($property.Name -in @('attributes', 'relationships')) { continue }
    Write-Value -Path "data.$($property.Name)" -Value $property.Value
}

$attributes = Get-PropertyValue -Object $data -Names @('attributes')
Write-Host ''
Write-Host '--- ATTRIBUTES ---' -ForegroundColor Yellow
if ($null -eq $attributes) {
    Write-Host '<no attributes object>'
}
else {
    foreach ($property in @($attributes.PSObject.Properties | Sort-Object Name)) {
        Write-Value -Path "attributes.$($property.Name)" -Value $property.Value
    }
}

Write-Host ''
Write-Host '--- DATE/CLOSE CANDIDATES ONLY ---' -ForegroundColor Yellow
$candidates = [System.Collections.Generic.List[object]]::new()

function Find-Candidates {
    param(
        [AllowNull()]$Object,
        [string]$Path = 'data'
    )

    if ($null -eq $Object) { return }

    if ($Object -is [string] -or $Object.GetType().IsPrimitive -or $Object -is [decimal] -or $Object -is [datetime]) {
        return
    }

    if ($Object -is [System.Collections.IDictionary]) {
        foreach ($key in $Object.Keys) {
            $childPath = "$Path.$key"
            if ([string]$key -match '(?i)(close|date|due|expected)') {
                $candidates.Add([pscustomobject]@{ Path = $childPath; Value = [string]$Object[$key] })
            }
            Find-Candidates -Object $Object[$key] -Path $childPath
        }
        return
    }

    if ($Object -is [System.Collections.IEnumerable] -and -not ($Object -is [string])) {
        $i = 0
        foreach ($item in $Object) {
            Find-Candidates -Object $item -Path "$Path[$i]"
            $i++
        }
        return
    }

    foreach ($property in @($Object.PSObject.Properties)) {
        $childPath = "$Path.$($property.Name)"
        if ($property.Name -match '(?i)(close|date|due|expected)') {
            $candidates.Add([pscustomobject]@{ Path = $childPath; Value = [string]$property.Value })
        }
        Find-Candidates -Object $property.Value -Path $childPath
    }
}

Find-Candidates -Object $data

if ($candidates.Count -eq 0) {
    Write-Host 'No field name containing close/date/due/expected was returned.' -ForegroundColor Red
}
else {
    $candidates | Sort-Object Path -Unique | Format-Table -AutoSize -Wrap
}

Write-Host ''
Write-Host 'Inspection complete. Paste the output back into ChatGPT.' -ForegroundColor Green
