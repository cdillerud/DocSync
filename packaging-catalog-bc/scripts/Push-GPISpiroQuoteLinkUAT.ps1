[CmdletBinding()]
param(
    [int]$QuoteNo = 55,
    [switch]$Apply,
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

function Invoke-BcRequest {
    param(
        [Parameter(Mandatory)][ValidateSet('GET','PATCH')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token,
        [AllowNull()]$Body,
        [string]$IfMatch = ''
    )

    $headers = @{ Authorization = "Bearer $Token"; Accept = 'application/json' }
    if (-not [string]::IsNullOrWhiteSpace($IfMatch)) { $headers['If-Match'] = $IfMatch }

    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -TimeoutSec $TimeoutSeconds
    }

    return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -ContentType 'application/json' -Body ($Body | ConvertTo-Json -Depth 20 -Compress) -TimeoutSec $TimeoutSeconds
}

Write-Section 'GPI SPIRO QUOTE LINK WRITEBACK UAT'
Write-Host "Environment : $EnvironmentName"
Write-Host "Quote No.   : $QuoteNo"
Write-Host "Write mode  : $($Apply.IsPresent)"
Write-Host 'Scope       : Spiro custom.bc_packaging_quote only' -ForegroundColor Green
Write-Host 'BC pricing, margin, approval, guardrail, audit, and quote lines are not modified.' -ForegroundColor Green

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
if ([string]::IsNullOrWhiteSpace($bcToken)) { throw 'BC authentication did not return an access token.' }

$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companies = Invoke-BcRequest -Method GET -Uri "$bcBase/api/v2.0/companies" -Token $bcToken -Body $null
$company = @($companies.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
if (-not $company) { throw "BC company '$CompanyName' not found." }

$companyId = [string]$company.id
$spiroBase = "$bcBase/api/gpi/spiroIntegration/v1.0/companies($companyId)"
$quoteListUri = "$spiroBase/spiroQuoteLinks?`$filter=quoteNo eq $QuoteNo"
$quoteResponse = Invoke-BcRequest -Method GET -Uri $quoteListUri -Token $bcToken -Body $null
$quote = @($quoteResponse.value) | Select-Object -First 1
if (-not $quote) { throw "Packaging Quote $QuoteNo was not returned by the Spiro quote-link API." }

$opportunityId = [string]$quote.spiroOpportunityId
if ([string]::IsNullOrWhiteSpace($opportunityId)) { throw "Packaging Quote $QuoteNo is not linked to a Spiro opportunity." }

Write-Host "Customer             : $($quote.customerNo) | $($quote.customerName)"
Write-Host "Spiro Opportunity ID : $opportunityId"
Write-Host "Opportunity Name     : $($quote.spiroOpportunityName)"

$encodedCompany = [uri]::EscapeDataString($CompanyName)
$filterText = "'Entry No.' IS '$QuoteNo'"
$encodedFilter = [uri]::EscapeDataString($filterText)
$quoteUrl = "https://businesscentral.dynamics.com/$TenantId/${EnvironmentName}?company=$encodedCompany&page=71010&filter=$encodedFilter"

Write-Host "BC Quote URL          : $quoteUrl"

Write-Section 'LOAD CURRENT SPIRO TARGET'
if (-not (Test-Path -LiteralPath $TokenStorePath)) { throw "Spiro token store not found: $TokenStorePath" }
$root = Import-Clixml -LiteralPath $TokenStorePath
$container = Get-TokenContainer -Root $root
$spiroToken = Convert-SecretValueToText -Value (Get-PropertyValue $container @('AccessToken','access_token','accessToken','Token'))
if ([string]::IsNullOrWhiteSpace($spiroToken)) { throw 'No Spiro access token found.' }

$spiroHeaders = @{ Authorization = "Bearer $spiroToken"; Accept = 'application/json'; 'X-Api-Version' = '1' }
$spiroUri = "https://api.spiro.ai/api/v1/opportunities/${opportunityId}"
$currentResponse = Invoke-RestMethod -Method GET -Uri $spiroUri -Headers $spiroHeaders -TimeoutSec $TimeoutSeconds
$currentData = Get-PropertyValue $currentResponse @('data')
if ($currentData -is [System.Array]) { $currentData = @($currentData) | Select-Object -First 1 }
if ($null -eq $currentData) { $currentData = $currentResponse }
$currentAttributes = Get-PropertyValue $currentData @('attributes')
$currentCustom = Get-PropertyValue $currentAttributes @('custom','custom_fields','customFields')
$targetProperty = $null
if ($null -ne $currentCustom) {
    $targetProperty = $currentCustom.PSObject.Properties | Where-Object { $_.Name -ieq 'bc_packaging_quote' } | Select-Object -First 1
}
if (-not $targetProperty) { throw 'Dedicated Spiro custom field bc_packaging_quote was not returned. Re-run the 0.21 preflight.' }

$currentValue = [string]$targetProperty.Value
Write-Host "Target field  : bc_packaging_quote"
Write-Host "Current value : $currentValue"
Write-Host "Desired value : $quoteUrl"

$payload = [ordered]@{
    data = [ordered]@{
        type = [string](Get-PropertyValue $currentData @('type'))
        id = $opportunityId
        attributes = [ordered]@{
            custom = [ordered]@{
                bc_packaging_quote = $quoteUrl
            }
        }
    }
}

if (-not $Apply) {
    Write-Section 'DRY RUN COMPLETE'
    if ($currentValue -eq $quoteUrl) {
        Write-Host 'Spiro already contains the desired Business Central quote link.' -ForegroundColor Green
    }
    else {
        Write-Host 'No records were changed.' -ForegroundColor Green
        Write-Host 'The next controlled run would update only custom.bc_packaging_quote on this Spiro opportunity.'
    }
    Write-Host ''
    Write-Host 'Proposed Spiro request:' -ForegroundColor Yellow
    Write-Host "PUT $spiroUri"
    $payload | ConvertTo-Json -Depth 10
    Write-Host ''
    Write-Host 'Re-run with -Apply only after reviewing this dry run.' -ForegroundColor Cyan
    return
}

Write-Section 'WRITE CONFIRMATION'
Write-Host "Spiro Opportunity : $opportunityId | $($quote.spiroOpportunityName)"
Write-Host 'Field             : bc_packaging_quote'
Write-Host "New value         : $quoteUrl"
Write-Host 'No other Spiro field is included in the update payload.' -ForegroundColor Green
$confirmation = Read-Host 'Type PUSH to continue'
if ($confirmation -cne 'PUSH') { throw 'Writeback cancelled. No Spiro record was changed.' }

Write-Section 'APPLY SPIRO QUOTE LINK'
try {
    $putHeaders = @{
        Authorization = "Bearer $spiroToken"
        Accept = 'application/json'
        'X-Api-Version' = '1'
        'Content-Type' = 'application/json'
    }
    Invoke-RestMethod -Method PUT -Uri $spiroUri -Headers $putHeaders -Body ($payload | ConvertTo-Json -Depth 10 -Compress) -TimeoutSec $TimeoutSeconds | Out-Null
}
catch {
    $message = "Spiro quote-link push failed: $($_.Exception.Message)"
    $statusBody = [ordered]@{
        spiroPushStatus = 'Failed'
        spiroLastPushedAt = [datetime]::UtcNow.ToString('o')
        spiroLastPushedBy = [Environment]::UserName
        spiroPushMessage = $message.Substring(0, [Math]::Min(250, $message.Length))
    }
    $quoteId = [string]$quote.id
    if (-not [string]::IsNullOrWhiteSpace($quoteId)) {
        try { Invoke-BcRequest -Method PATCH -Uri "$spiroBase/spiroQuoteLinks($quoteId)" -Token $bcToken -Body $statusBody -IfMatch '*' | Out-Null } catch { }
    }
    throw $message
}

Write-Section 'VERIFY SPIRO WRITEBACK'
$verifyResponse = Invoke-RestMethod -Method GET -Uri $spiroUri -Headers $spiroHeaders -TimeoutSec $TimeoutSeconds
$verifyData = Get-PropertyValue $verifyResponse @('data')
if ($verifyData -is [System.Array]) { $verifyData = @($verifyData) | Select-Object -First 1 }
if ($null -eq $verifyData) { $verifyData = $verifyResponse }
$verifyAttrs = Get-PropertyValue $verifyData @('attributes')
$verifyCustom = Get-PropertyValue $verifyAttrs @('custom','custom_fields','customFields')
$verifiedValue = [string](Get-PropertyValue $verifyCustom @('bc_packaging_quote'))
if ($verifiedValue -ne $quoteUrl) {
    throw "Spiro verification failed. Expected '$quoteUrl' but received '$verifiedValue'."
}

$statusBody = [ordered]@{
    spiroPushStatus = 'Success'
    spiroLastPushedAt = [datetime]::UtcNow.ToString('o')
    spiroLastPushedBy = [Environment]::UserName
    spiroPushMessage = 'Business Central packaging quote link verified in Spiro.'
}
$quoteId = [string]$quote.id
if ([string]::IsNullOrWhiteSpace($quoteId)) { throw 'BC quote API row did not include its SystemId for writeback status tracking.' }
Invoke-BcRequest -Method PATCH -Uri "$spiroBase/spiroQuoteLinks($quoteId)" -Token $bcToken -Body $statusBody -IfMatch '*' | Out-Null

Write-Host "Verified Spiro value : $verifiedValue" -ForegroundColor Green
Write-Host 'BC push status        : Success' -ForegroundColor Green
Write-Host 'SUCCESS: Spiro now contains the verified Business Central packaging quote link.' -ForegroundColor Green
