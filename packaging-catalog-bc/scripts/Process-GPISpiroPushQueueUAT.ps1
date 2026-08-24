[CmdletBinding()]
param(
    [int]$EntryNo = 1,
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
        if ($null -ne $candidate -and $null -ne (Get-PropertyValue $candidate @('AccessToken','access_token','accessToken','Token'))) { return $candidate }
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
    if ($null -eq $Body) { return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -TimeoutSec $TimeoutSeconds }
    return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -ContentType 'application/json' -Body ($Body | ConvertTo-Json -Depth 20 -Compress) -TimeoutSec $TimeoutSeconds
}

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') { throw "This worker is restricted to Sandbox_NoZetadocs_UAT. Requested: $EnvironmentName" }
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'Azure CLI (az) is required.' }

Write-Section 'GPI SPIRO PUSH QUEUE WORKER UAT'
Write-Host "Queue Entry : $EntryNo"
Write-Host "Apply       : $($Apply.IsPresent)"
Write-Host 'Idempotent behavior: skip Spiro PUT when the desired quote link is already present.' -ForegroundColor Green

$secret = (& az keyvault secret show --vault-name $KeyVaultName --name 'bc-client-secret' --query value --output tsv --only-show-errors).Trim()
if ([string]::IsNullOrWhiteSpace($secret)) { throw 'Could not retrieve BC client secret.' }
try {
    $bcAuth = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType 'application/x-www-form-urlencoded' -Body @{
        grant_type = 'client_credentials'; client_id = $BcClientId; client_secret = $secret; scope = 'https://api.businesscentral.dynamics.com/.default'
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

Write-Section 'LOAD QUEUED REQUEST'
$queueListUri = "$spiroBase/spiroPushRequests?`$filter=entryNo eq $EntryNo"
$queueResponse = Invoke-BcRequest -Method GET -Uri $queueListUri -Token $bcToken -Body $null
$queue = @($queueResponse.value) | Select-Object -First 1
if (-not $queue) { throw "Spiro push queue entry $EntryNo was not found." }
if ([string]$queue.status -ne 'Queued') { throw "Queue entry $EntryNo is not Queued. Current status: $($queue.status)" }

$quoteNo = [int]$queue.quoteNo
$opportunityId = [string]$queue.spiroOpportunityId
Write-Host "Quote No.            : $quoteNo"
Write-Host "Spiro Opportunity ID : $opportunityId"
Write-Host "Requested By         : $($queue.requestedBy)"
Write-Host "Requested At         : $($queue.requestedAt)"

$quoteListUri = "$spiroBase/spiroQuoteLinks?`$filter=quoteNo eq $quoteNo"
$quoteResponse = Invoke-BcRequest -Method GET -Uri $quoteListUri -Token $bcToken -Body $null
$quote = @($quoteResponse.value) | Select-Object -First 1
if (-not $quote) { throw "Packaging Quote $quoteNo was not returned by the Spiro quote-link API." }
if ([string]$quote.spiroOpportunityId -ne $opportunityId) { throw 'Queued opportunity no longer matches the opportunity currently linked to the quote.' }

$encodedCompany = [uri]::EscapeDataString($CompanyName)
$filterText = "'Entry No.' IS '$quoteNo'"
$encodedFilter = [uri]::EscapeDataString($filterText)
$quoteUrl = "https://businesscentral.dynamics.com/$TenantId/${EnvironmentName}?company=$encodedCompany&page=71010&filter=$encodedFilter"
Write-Host "Desired BC Quote URL : $quoteUrl"

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
$currentValue = [string](Get-PropertyValue $currentCustom @('bc_packaging_quote'))

Write-Section 'COMPARE SPIRO VALUE'
Write-Host "Current value : $currentValue"
Write-Host "Desired value : $quoteUrl"
$needsPut = $currentValue -ne $quoteUrl
if ($needsPut) { Write-Host 'Worker action : PUT required' -ForegroundColor Yellow }
else { Write-Host 'Worker action : SKIP PUT, value already matches' -ForegroundColor Green }

if (-not $Apply) {
    Write-Section 'DRY RUN COMPLETE'
    Write-Host 'No records were changed.' -ForegroundColor Green
    Write-Host 'Re-run with -Apply after reviewing this comparison.' -ForegroundColor Cyan
    return
}

if ($needsPut) {
    $payload = [ordered]@{ data = [ordered]@{ type = [string](Get-PropertyValue $currentData @('type')); id = $opportunityId; attributes = [ordered]@{ custom = [ordered]@{ bc_packaging_quote = $quoteUrl } } } }
    $putHeaders = @{ Authorization = "Bearer $spiroToken"; Accept = 'application/json'; 'X-Api-Version' = '1'; 'Content-Type' = 'application/json' }
    Invoke-RestMethod -Method PUT -Uri $spiroUri -Headers $putHeaders -Body ($payload | ConvertTo-Json -Depth 10 -Compress) -TimeoutSec $TimeoutSeconds | Out-Null
}

$verifyResponse = Invoke-RestMethod -Method GET -Uri $spiroUri -Headers $spiroHeaders -TimeoutSec $TimeoutSeconds
$verifyData = Get-PropertyValue $verifyResponse @('data')
if ($verifyData -is [System.Array]) { $verifyData = @($verifyData) | Select-Object -First 1 }
if ($null -eq $verifyData) { $verifyData = $verifyResponse }
$verifyAttrs = Get-PropertyValue $verifyData @('attributes')
$verifyCustom = Get-PropertyValue $verifyAttrs @('custom','custom_fields','customFields')
$verifiedValue = [string](Get-PropertyValue $verifyCustom @('bc_packaging_quote'))
if ($verifiedValue -ne $quoteUrl) { throw "Spiro verification failed. Expected '$quoteUrl' but received '$verifiedValue'." }

$now = [datetime]::UtcNow.ToString('o')
$workerUser = [Environment]::UserName
$queueMessage = if ($needsPut) { 'Business Central packaging quote link written to Spiro and verified.' } else { 'Spiro already contained the Business Central packaging quote link; write skipped and value verified.' }

$queueId = [string]$queue.id
$quoteId = [string]$quote.id
if ([string]::IsNullOrWhiteSpace($queueId) -or [string]::IsNullOrWhiteSpace($quoteId)) { throw 'BC API rows did not include SystemId values needed for completion updates.' }

Invoke-BcRequest -Method PATCH -Uri "$spiroBase/spiroPushRequests($queueId)" -Token $bcToken -IfMatch '*' -Body ([ordered]@{ status = 'Success'; processedAt = $now; message = $queueMessage }) | Out-Null
Invoke-BcRequest -Method PATCH -Uri "$spiroBase/spiroQuoteLinks($quoteId)" -Token $bcToken -IfMatch '*' -Body ([ordered]@{ spiroPushStatus = 'Success'; spiroLastPushedAt = $now; spiroLastPushedBy = $workerUser; spiroPushMessage = $queueMessage }) | Out-Null

Write-Section 'WORKER COMPLETE'
Write-Host "Verified Spiro value : $verifiedValue" -ForegroundColor Green
Write-Host "Queue Entry $EntryNo     : Success" -ForegroundColor Green
Write-Host "Quote $quoteNo push status : Success" -ForegroundColor Green
if ($needsPut) { Write-Host 'Spiro PUT performed      : Yes' }
else { Write-Host 'Spiro PUT performed      : No, existing value matched' }
Write-Host 'SUCCESS: queued writeback request processed and verified.' -ForegroundColor Green
