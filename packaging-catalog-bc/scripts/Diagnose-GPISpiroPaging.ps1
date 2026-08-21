[CmdletBinding()]
param(
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml",
    [int]$PageSize = 100,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ApiBase = 'https://api.spiro.ai/api/v1'

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

function Get-CompanyName {
    param([AllowNull()]$Record)

    if ($null -eq $Record) { return '' }
    $attributes = Get-PropertyValue -Object $Record -Names @('attributes')
    if ($null -ne $attributes) {
        $name = Get-PropertyValue -Object $attributes -Names @('name','company_name','display_name')
        if ($null -ne $name) { return [string]$name }
    }

    return [string](Get-PropertyValue -Object $Record -Names @('name','company_name','display_name'))
}

function Get-RecordId {
    param([AllowNull()]$Record)
    return [string](Get-PropertyValue -Object $Record -Names @('id','Id','_id'))
}

function Invoke-SpiroPage {
    param(
        [Parameter(Mandatory)][int]$Page,
        [Parameter(Mandatory)][string]$AccessToken,
        [switch]$Encoded
    )

    if ($Encoded) {
        $uri = "$ApiBase/companies?page%5Bnumber%5D=$Page&page%5Bsize%5D=$PageSize"
    }
    else {
        $uri = "$ApiBase/companies?page[number]=$Page&page[size]=$PageSize"
    }

    $headers = @{
        Authorization = "Bearer $AccessToken"
        Accept = 'application/json'
        'X-Api-Version' = '1'
    }

    return Invoke-RestMethod -Method GET -Uri $uri -Headers $headers -TimeoutSec $TimeoutSeconds
}

function Get-DataRows {
    param([Parameter(Mandatory)]$Response)

    if ($Response.PSObject.Properties.Name -contains 'data') {
        return @($Response.data)
    }
    if ($Response.PSObject.Properties.Name -contains 'companies') {
        return @($Response.companies)
    }
    return @($Response)
}

function Show-PageSummary {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)]$Response
    )

    $rows = @(Get-DataRows -Response $Response)
    $ids = @($rows | ForEach-Object { Get-RecordId -Record $_ })

    Write-Host ''
    Write-Host $Label -ForegroundColor Cyan
    Write-Host "Rows               : $($rows.Count)"
    Write-Host "Unique IDs         : $(@($ids | Where-Object { $_ } | Sort-Object -Unique).Count)"
    Write-Host "Top-level fields   : $($Response.PSObject.Properties.Name -join ', ')"

    if ($Response.PSObject.Properties.Name -contains 'meta') {
        Write-Host 'Meta:'
        $Response.meta | ConvertTo-Json -Depth 10
    }
    else {
        Write-Host 'Meta               : <none>'
    }

    Write-Host 'First 5 rows:'
    $rows |
        Select-Object -First 5 |
        ForEach-Object {
            [pscustomobject]@{
                Id = Get-RecordId -Record $_
                Name = Get-CompanyName -Record $_
            }
        } |
        Format-Table -AutoSize

    Write-Host 'Last 5 rows:'
    $rows |
        Select-Object -Last 5 |
        ForEach-Object {
            [pscustomobject]@{
                Id = Get-RecordId -Record $_
                Name = Get-CompanyName -Record $_
            }
        } |
        Format-Table -AutoSize

    return [pscustomobject]@{
        Rows = $rows
        Ids = $ids
    }
}

if (-not (Test-Path -LiteralPath $TokenStorePath)) {
    throw "Spiro token store not found: $TokenStorePath"
}

$root = Import-Clixml -LiteralPath $TokenStorePath
$container = Get-TokenContainer -Root $root
$tokenValue = Get-PropertyValue -Object $container -Names @('AccessToken','access_token','accessToken','Token')
$accessToken = Convert-SecretToText -Value $tokenValue

if ([string]::IsNullOrWhiteSpace($accessToken)) {
    throw 'No Spiro access token was found in the protected token store.'
}

Write-Host ''
Write-Host '========================================================================' -ForegroundColor Cyan
Write-Host 'GPI SPIRO PAGINATION DIAGNOSTIC' -ForegroundColor Cyan
Write-Host '========================================================================' -ForegroundColor Cyan
Write-Host "Token store : $TokenStorePath"
Write-Host "Page size   : $PageSize"
Write-Host 'No Business Central calls or writes are performed by this script.' -ForegroundColor Green

$page1Encoded = Invoke-SpiroPage -Page 1 -AccessToken $accessToken -Encoded
$page2Encoded = Invoke-SpiroPage -Page 2 -AccessToken $accessToken -Encoded
$page2Plain = Invoke-SpiroPage -Page 2 -AccessToken $accessToken

$p1 = Show-PageSummary -Label 'ENCODED PAGE 1' -Response $page1Encoded
$p2e = Show-PageSummary -Label 'ENCODED PAGE 2' -Response $page2Encoded
$p2p = Show-PageSummary -Label 'PLAIN PAGE 2' -Response $page2Plain

$ids1 = @($p1.Ids | Where-Object { $_ })
$ids2e = @($p2e.Ids | Where-Object { $_ })
$ids2p = @($p2p.Ids | Where-Object { $_ })

$encodedOverlap = @($ids1 | Where-Object { $_ -in $ids2e }).Count
$plainOverlap = @($ids1 | Where-Object { $_ -in $ids2p }).Count

Write-Host ''
Write-Host '========================================================================' -ForegroundColor Cyan
Write-Host 'COMPARISON' -ForegroundColor Cyan
Write-Host '========================================================================' -ForegroundColor Cyan
Write-Host "Encoded page 1/page 2 overlap : $encodedOverlap of $($ids1.Count)"
Write-Host "Plain page 1/page 2 overlap   : $plainOverlap of $($ids1.Count)"

$sampleRows = @($p1.Rows + $p2e.Rows) |
    ForEach-Object {
        [pscustomobject]@{
            Id = Get-RecordId -Record $_
            Name = Get-CompanyName -Record $_
        }
    } |
    Where-Object { $_.Name -match '(?i)wat|jr|j\.r\.' } |
    Sort-Object Id -Unique

Write-Host ''
Write-Host 'Wat/JR-like names found on encoded pages 1-2:'
if ($sampleRows.Count -eq 0) {
    Write-Host '<none>'
}
else {
    $sampleRows | Format-Table -AutoSize
}

$accessToken = $null

Write-Host ''
Write-Host 'Diagnostic complete.' -ForegroundColor Green
