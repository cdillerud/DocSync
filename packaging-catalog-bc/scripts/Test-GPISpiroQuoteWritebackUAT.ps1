[CmdletBinding()]
param(
    [int]$QuoteNo = 55,
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$BcClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [string]$TokenStorePath = "$env:LOCALAPPDATA\GPI\SpiroOAuth\spiro-oauth-uat.clixml",
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-PropertyValue {
    param([AllowNull()]$Object, [Parameter(Mandatory)][string[]]$Names)
    if ($null -eq $Object) { return $null }
    foreach ($name in $Names) {
        $p = $Object.PSObject.Properties | Where-Object { $_.Name -ieq $name } | Select-Object -First 1
        if ($p) { return $p.Value }
    }
    return $null
}

function Convert-SecretValueToText {
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
    foreach ($candidate in @($Root, (Get-PropertyValue $Root @('Tokens','TokenData','OAuth','OAuthTokens','SpiroTokens')))) {
        if ($null -ne $candidate -and $null -ne (Get-PropertyValue $candidate @('AccessToken','access_token','accessToken','Token'))) {
            return $candidate
        }
    }
    return $Root
}

Write-Host ''
Write-Host '========================================================================' -ForegroundColor Cyan
Write-Host 'GPI SPIRO QUOTE WRITEBACK UAT PREFLIGHT' -ForegroundColor Cyan
Write-Host '========================================================================' -ForegroundColor Cyan
Write-Host 'READ ONLY. No Business Central or Spiro writes will be performed.' -ForegroundColor Green

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "This preflight is restricted to Sandbox_NoZetadocs_UAT. Requested: $EnvironmentName"
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'Azure CLI (az) is required.' }

$secret = (& az keyvault secret show --vault-name $KeyVaultName --name 'bc-client-secret' --query value --output tsv --only-show-errors).Trim()
if ([string]::IsNullOrWhiteSpace($secret)) { throw 'Could not retrieve BC client secret.' }
try {
    $bcAuth = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType 'application/x-www-form-urlencoded' -Body @{
        grant_type = 'client_credentials'
        client_id = $BcClientId
        client_secret = $secret
        scope = 'https://api.businesscentral.dynamics.com/.default'
    } -TimeoutSec $TimeoutSeconds
}
finally { $secret = $null }

$bcToken = [string]$bcAuth.access_token
$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companies = Invoke-RestMethod -Method GET -Uri "$bcBase/api/v2.0/companies" -Headers @{ Authorization = "Bearer $bcToken"; Accept = 'application/json' } -TimeoutSec $TimeoutSeconds
$company = @($companies.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
if (-not $company) { throw "BC company '$CompanyName' not found." }

$companyId = [string]$company.id
$quoteUri = "$bcBase/api/gpi/spiroIntegration/v1.0/companies($companyId)/spiroQuoteLinks?`$filter=quoteNo eq $QuoteNo"
$quoteResponse = Invoke-RestMethod -Method GET -Uri $quoteUri -Headers @{ Authorization = "Bearer $bcToken"; Accept = 'application/json' } -TimeoutSec $TimeoutSeconds
$quote = @($quoteResponse.value) | Select-Object -First 1
if (-not $quote) { throw "Packaging Quote $QuoteNo was not returned by the Spiro quote-link API." }

$opportunityId = [string]$quote.spiroOpportunityId
if ([string]::IsNullOrWhiteSpace($opportunityId)) {
    throw "Packaging Quote $QuoteNo is not linked to a Spiro opportunity. Select a Spiro opportunity first."
}

Write-Host "Quote No.            : $QuoteNo"
Write-Host "Customer             : $($quote.customerNo) | $($quote.customerName)"
Write-Host "Spiro Opportunity ID : $opportunityId"
Write-Host "Opportunity Name     : $($quote.spiroOpportunityName)"

if (-not (Test-Path -LiteralPath $TokenStorePath)) { throw "Spiro token store not found: $TokenStorePath" }
$root = Import-Clixml -LiteralPath $TokenStorePath
$container = Get-TokenContainer -Root $root
$spiroToken = Convert-SecretValueToText -Value (Get-PropertyValue $container @('AccessToken','access_token','accessToken','Token'))
if ([string]::IsNullOrWhiteSpace($spiroToken)) { throw 'No Spiro access token found.' }

$spiroUri = "https://api.spiro.ai/api/v1/opportunities/${opportunityId}?include=user"
$response = Invoke-RestMethod -Method GET -Uri $spiroUri -Headers @{ Authorization = "Bearer $spiroToken"; Accept = 'application/json'; 'X-Api-Version' = '1' } -TimeoutSec $TimeoutSeconds
$data = Get-PropertyValue $response @('data')
if ($data -is [System.Array]) { $data = @($data) | Select-Object -First 1 }
if ($null -eq $data) { $data = $response }
$attributes = Get-PropertyValue $data @('attributes')
$custom = Get-PropertyValue $attributes @('custom','custom_fields','customFields')

Write-Host ''
Write-Host '--- SPIRO WRITEBACK TARGET DISCOVERY ---' -ForegroundColor Yellow
$aliases = @(
    'bc_packaging_quote',
    'bc_packaging_quote_url',
    'business_central_packaging_quote',
    'business_central_quote',
    'bc_quote_url'
)

$found = $null
foreach ($alias in $aliases) {
    $p = $null
    if ($null -ne $custom) {
        $p = $custom.PSObject.Properties | Where-Object { $_.Name -ieq $alias } | Select-Object -First 1
    }
    if ($p) {
        $found = $p
        break
    }
}

if ($found) {
    Write-Host "PASS: dedicated Spiro quote-link target found: $($found.Name)" -ForegroundColor Green
    Write-Host "Current value: $($found.Value)"
    Write-Host ''
    Write-Host 'Writeback target is ready for the next controlled slice.' -ForegroundColor Green
}
else {
    Write-Host 'No dedicated BC Packaging Quote custom field exists on this Spiro opportunity.' -ForegroundColor Yellow
    Write-Host 'Recommended Spiro setup:' -ForegroundColor Cyan
    Write-Host '  Entity : Opportunity'
    Write-Host '  Label  : BC Packaging Quote'
    Write-Host '  Type   : Link'
    Write-Host ''
    Write-Host 'Do not repurpose description, external_id, or sharepoint_docs_opportunity.' -ForegroundColor Green
}

Write-Host ''
Write-Host 'Preflight complete. No records were changed.' -ForegroundColor Green