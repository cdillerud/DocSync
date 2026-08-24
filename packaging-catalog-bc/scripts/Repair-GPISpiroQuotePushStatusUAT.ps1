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

function Write-Section {
    param([Parameter(Mandatory)][string]$Text)
    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 72) -ForegroundColor Cyan
}

Write-Section 'GPI SPIRO QUOTE PUSH STATUS REPAIR UAT'
Write-Host 'This script does not write to Spiro.' -ForegroundColor Green
Write-Host 'It verifies the existing Spiro quote link, then repairs BC tracking only.' -ForegroundColor Green

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "This script is restricted to Sandbox_NoZetadocs_UAT. Requested: $EnvironmentName"
}
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'Azure CLI (az) is required.' }

Write-Section 'LOAD BUSINESS CENTRAL QUOTE LINK'
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
$bcHeaders = @{ Authorization = "Bearer $bcToken"; Accept = 'application/json' }
$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companies = Invoke-RestMethod -Method GET -Uri "$bcBase/api/v2.0/companies" -Headers $bcHeaders -TimeoutSec $TimeoutSeconds
$company = @($companies.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
if (-not $company) { throw "BC company '$CompanyName' not found." }

$companyId = [string]$company.id
$spiroBase = "$bcBase/api/gpi/spiroIntegration/v1.0/companies($companyId)"
$quoteListUri = "$spiroBase/spiroQuoteLinks?`$filter=quoteNo eq $QuoteNo"
$quoteResponse = Invoke-RestMethod -Method GET -Uri $quoteListUri -Headers $bcHeaders -TimeoutSec $TimeoutSeconds
$quote = @($quoteResponse.value) | Select-Object -First 1
if (-not $quote) { throw "Packaging Quote $QuoteNo was not returned by the Spiro quote-link API." }

if (-not ($quote.PSObject.Properties.Name -contains 'spiroPushStatus')) {
    throw 'BC is still serving the pre-0.21 Spiro Quote Link API schema. Publish GPI Packaging Catalog_0.21.0.0.app to Sandbox_NoZetadocs_UAT, then rerun this script.'
}

$opportunityId = [string]$quote.spiroOpportunityId
if ([string]::IsNullOrWhiteSpace($opportunityId)) { throw "Packaging Quote $QuoteNo is not linked to a Spiro opportunity." }

$encodedCompany = [uri]::EscapeDataString($CompanyName)
$filterText = "'Entry No.' IS '$QuoteNo'"
$encodedFilter = [uri]::EscapeDataString($filterText)
$quoteUrl = "https://businesscentral.dynamics.com/$TenantId/${EnvironmentName}?company=$encodedCompany&page=71010&filter=$encodedFilter"

Write-Host "Quote No.            : $QuoteNo"
Write-Host "Spiro Opportunity ID : $opportunityId"
Write-Host "Expected Spiro link  : $quoteUrl"

Write-Section 'VERIFY EXISTING SPIRO VALUE'
if (-not (Test-Path -LiteralPath $TokenStorePath)) { throw "Spiro token store not found: $TokenStorePath" }
$root = Import-Clixml -LiteralPath $TokenStorePath
$container = Get-TokenContainer -Root $root
$spiroToken = Convert-SecretValueToText -Value (Get-PropertyValue $container @('AccessToken','access_token','accessToken','Token'))
if ([string]::IsNullOrWhiteSpace($spiroToken)) { throw 'No Spiro access token found.' }

$spiroUri = "https://api.spiro.ai/api/v1/opportunities/${opportunityId}"
$spiroHeaders = @{ Authorization = "Bearer $spiroToken"; Accept = 'application/json'; 'X-Api-Version' = '1' }
$response = Invoke-RestMethod -Method GET -Uri $spiroUri -Headers $spiroHeaders -TimeoutSec $TimeoutSeconds
$data = Get-PropertyValue $response @('data')
if ($data -is [System.Array]) { $data = @($data) | Select-Object -First 1 }
if ($null -eq $data) { $data = $response }
$attrs = Get-PropertyValue $data @('attributes')
$custom = Get-PropertyValue $attrs @('custom','custom_fields','customFields')
$actualValue = [string](Get-PropertyValue $custom @('bc_packaging_quote'))

Write-Host "Actual Spiro link    : $actualValue"
if ($actualValue -ne $quoteUrl) {
    throw 'Spiro does not contain the expected BC Packaging Quote link. BC status will not be repaired.'
}
Write-Host 'PASS: Spiro already contains the verified Business Central quote link.' -ForegroundColor Green

Write-Section 'REPAIR BC PUSH STATUS'
$quoteId = [string]$quote.id
if ([string]::IsNullOrWhiteSpace($quoteId)) { throw 'BC quote API row did not include its SystemId.' }

$statusBody = [ordered]@{
    spiroPushStatus = 'Success'
    spiroLastPushedAt = [datetime]::UtcNow.ToString('o')
    spiroLastPushedBy = [Environment]::UserName
    spiroPushMessage = 'Business Central packaging quote link verified in Spiro; BC tracking repaired after successful push.'
}

$patchHeaders = @{
    Authorization = "Bearer $bcToken"
    Accept = 'application/json'
    'If-Match' = '*'
}
$patchUri = "$spiroBase/spiroQuoteLinks($quoteId)"
Invoke-RestMethod -Method PATCH -Uri $patchUri -Headers $patchHeaders -ContentType 'application/json' -Body ($statusBody | ConvertTo-Json -Depth 10 -Compress) -TimeoutSec $TimeoutSeconds | Out-Null

$verifyResponse = Invoke-RestMethod -Method GET -Uri $quoteListUri -Headers $bcHeaders -TimeoutSec $TimeoutSeconds
$verifyQuote = @($verifyResponse.value) | Select-Object -First 1
if (-not $verifyQuote) { throw 'Could not reload quote after BC status repair.' }
if ([string]$verifyQuote.spiroPushStatus -ne 'Success') { throw "BC status verification failed. Current status: $($verifyQuote.spiroPushStatus)" }

Write-Host "BC push status      : $($verifyQuote.spiroPushStatus)" -ForegroundColor Green
Write-Host "Last pushed at      : $($verifyQuote.spiroLastPushedAt)"
Write-Host "Last pushed by      : $($verifyQuote.spiroLastPushedBy)"
Write-Host "Push message        : $($verifyQuote.spiroPushMessage)"
Write-Host ''
Write-Host 'SUCCESS: Spiro link was verified and BC writeback tracking was repaired. No Spiro write was performed.' -ForegroundColor Green
