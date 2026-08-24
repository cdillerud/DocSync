[CmdletBinding(DefaultParameterSetName = 'Prepare')]
param(
    [Parameter(ParameterSetName = 'Prepare')][switch]$Prepare,
    [Parameter(ParameterSetName = 'Restore')][switch]$Restore,
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$BcClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [int]$QuoteEntryNo = 55,
    [string]$ExpectedCustomerNo = "WAT",
    [string]$ExpectedOpportunityId = "3463019",
    [string]$SentinelOwner = "GPI SYNC WRITE TEST",
    [string]$StatePath = "$env:TEMP\GPI-SpiroSyncWriteTest-Quote55.json",
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Section {
    param([Parameter(Mandatory)][string]$Text)

    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor Cyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('=' * 72) -ForegroundColor Cyan
}

function Get-BcAccessToken {
    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        throw 'Azure CLI (az) is required for Business Central authentication.'
    }

    $accountJson = & az account show --output json --only-show-errors 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($accountJson | Out-String))) {
        & az login --tenant $TenantId --only-show-errors | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw 'Azure login failed.'
        }
    }

    $secret = (& az keyvault secret show `
        --vault-name $KeyVaultName `
        --name 'bc-client-secret' `
        --query value `
        --output tsv `
        --only-show-errors).Trim()

    if ([string]::IsNullOrWhiteSpace($secret)) {
        throw "Could not retrieve bc-client-secret from Key Vault $KeyVaultName."
    }

    try {
        $response = Invoke-RestMethod `
            -Method POST `
            -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" `
            -ContentType 'application/x-www-form-urlencoded' `
            -Body @{
                grant_type = 'client_credentials'
                client_id = $BcClientId
                client_secret = $secret
                scope = 'https://api.businesscentral.dynamics.com/.default'
            } `
            -TimeoutSec $TimeoutSeconds
    }
    finally {
        $secret = $null
    }

    $token = [string]$response.access_token
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw 'Microsoft identity platform did not return a Business Central access token.'
    }

    return $token
}

function Invoke-BcRequest {
    param(
        [Parameter(Mandatory)][ValidateSet('GET','PATCH')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token,
        [AllowNull()]$Body,
        [string]$IfMatch = ''
    )

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = 'application/json'
    }

    if (-not [string]::IsNullOrWhiteSpace($IfMatch)) {
        $headers['If-Match'] = $IfMatch
    }

    if ($null -eq $Body) {
        return Invoke-RestMethod `
            -Method $Method `
            -Uri $Uri `
            -Headers $headers `
            -TimeoutSec $TimeoutSeconds
    }

    return Invoke-RestMethod `
        -Method $Method `
        -Uri $Uri `
        -Headers $headers `
        -ContentType 'application/json' `
        -Body ($Body | ConvertTo-Json -Depth 20 -Compress) `
        -TimeoutSec $TimeoutSeconds
}

function Get-QuoteLink {
    param(
        [Parameter(Mandatory)][string]$SpiroBase,
        [Parameter(Mandatory)][string]$Token
    )

    $filter = [uri]::EscapeDataString("quoteNo eq $QuoteEntryNo")
    $response = Invoke-BcRequest `
        -Method GET `
        -Uri "$SpiroBase/spiroQuoteLinks?`$filter=$filter" `
        -Token $Token `
        -Body $null

    return @($response.value) | Select-Object -First 1
}

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "This script is restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
}

if ($QuoteEntryNo -eq 67) {
    throw 'Quote 67 is protected and cannot be used for this test.'
}

if ($QuoteEntryNo -ne 55) {
    throw 'This controlled write-path test is restricted to Quote 55.'
}

if (-not $Prepare -and -not $Restore) {
    $Prepare = $true
}

Write-Section 'GPI SPIRO SYNC WRITE-PATH UAT TEST'
Write-Host "Mode              : $(if ($Restore) { 'Restore' } else { 'Prepare' })"
Write-Host "Environment       : $EnvironmentName"
Write-Host "Quote             : $QuoteEntryNo"
Write-Host "Expected customer : $ExpectedCustomerNo"
Write-Host "Expected Spiro opp: $ExpectedOpportunityId"
Write-Host 'Commercial fields : never modified' -ForegroundColor Green
Write-Host 'Contact fields    : never modified' -ForegroundColor Green

$bcToken = Get-BcAccessToken
$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companiesResponse = Invoke-BcRequest -Method GET -Uri "$bcBase/api/v2.0/companies" -Token $bcToken -Body $null
$bcCompany = @($companiesResponse.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
if (-not $bcCompany) {
    throw "Business Central company '$CompanyName' was not returned."
}

$bcCompanyId = [string]$bcCompany.id
$spiroBase = "$bcBase/api/gpi/spiroIntegration/v1.0/companies($bcCompanyId)"
$currentQuote = Get-QuoteLink -SpiroBase $spiroBase -Token $bcToken

if (-not $currentQuote) {
    throw "Packaging quote $QuoteEntryNo was not returned by the Spiro quote-link API."
}

if ([string]$currentQuote.customerNo -ne $ExpectedCustomerNo) {
    throw "Quote $QuoteEntryNo belongs to '$($currentQuote.customerNo)', not '$ExpectedCustomerNo'."
}

if ([string]$currentQuote.spiroOpportunityId -ne $ExpectedOpportunityId) {
    throw "Quote $QuoteEntryNo is linked to Spiro opportunity '$($currentQuote.spiroOpportunityId)', not '$ExpectedOpportunityId'."
}

if ([string]$currentQuote.status -ne 'Approved') {
    throw "Quote $QuoteEntryNo status is '$($currentQuote.status)', not 'Approved'."
}

Write-Section 'CURRENT CRM CONTEXT'
Write-Host "Quote status       : $($currentQuote.status)"
Write-Host "Spiro opportunity  : $($currentQuote.spiroOpportunityName) [$($currentQuote.spiroOpportunityId)]"
Write-Host "Spiro stage        : $($currentQuote.spiroStage)"
Write-Host "Spiro owner        : $($currentQuote.spiroOwner)"
Write-Host "Spiro contact      : $($currentQuote.spiroContactName) [$($currentQuote.spiroContactId)]"
Write-Host "Spiro browser URL  : $($currentQuote.spiroOpportunityUrl)"

$quoteId = [string]$currentQuote.id
if ([string]::IsNullOrWhiteSpace($quoteId)) {
    throw 'Quote link did not provide a BC API ID.'
}

if ($Restore) {
    if (-not (Test-Path -LiteralPath $StatePath)) {
        throw "Saved test state was not found: $StatePath"
    }

    $state = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    if ([int]$state.quoteNo -ne $QuoteEntryNo -or [string]$state.quoteId -ne $quoteId) {
        throw 'Saved test state does not match the current Quote 55 API record.'
    }

    Write-Section 'RESTORE CONFIRMATION'
    Write-Host "Owner to restore: $($state.spiroOwner)"
    $confirmation = Read-Host 'Type RESTORE to continue'
    if ($confirmation -cne 'RESTORE') {
        throw 'Restore cancelled. No Business Central records were changed.'
    }

    Invoke-BcRequest `
        -Method PATCH `
        -Uri "$spiroBase/spiroQuoteLinks($quoteId)" `
        -Token $bcToken `
        -Body ([ordered]@{ spiroOwner = [string]$state.spiroOwner }) `
        -IfMatch '*' | Out-Null

    $verified = Get-QuoteLink -SpiroBase $spiroBase -Token $bcToken
    if ([string]$verified.spiroOwner -ne [string]$state.spiroOwner) {
        throw 'Owner restore verification failed.'
    }

    Remove-Item -LiteralPath $StatePath -Force
    Write-Host "Quote $QuoteEntryNo owner restored to '$($verified.spiroOwner)'." -ForegroundColor Green
    Write-Host 'Saved test state removed.' -ForegroundColor Green
    return
}

if ([string]$currentQuote.spiroOwner -eq $SentinelOwner) {
    throw "Quote $QuoteEntryNo already contains the test sentinel owner. Use -Restore or run the sync engine to restore it."
}

$state = [ordered]@{
    quoteNo = $QuoteEntryNo
    quoteId = $quoteId
    customerNo = [string]$currentQuote.customerNo
    status = [string]$currentQuote.status
    spiroOpportunityId = [string]$currentQuote.spiroOpportunityId
    spiroOwner = [string]$currentQuote.spiroOwner
    savedAtUtc = [datetime]::UtcNow.ToString('o')
}

$state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StatePath -Encoding utf8NoBOM

Write-Section 'PREPARE WRITE-PATH TEST'
Write-Host "Saved rollback state: $StatePath"
Write-Host "Current owner        : $($currentQuote.spiroOwner)"
Write-Host "Temporary owner      : $SentinelOwner"
Write-Host 'Only the Spiro Owner CRM context field will be changed.' -ForegroundColor Yellow
Write-Host 'The repeatable sync engine should detect and restore this field from live Spiro.' -ForegroundColor Yellow

$confirmation = Read-Host 'Type TEST to continue'
if ($confirmation -cne 'TEST') {
    Remove-Item -LiteralPath $StatePath -Force -ErrorAction SilentlyContinue
    throw 'Test preparation cancelled. No Business Central records were changed.'
}

Invoke-BcRequest `
    -Method PATCH `
    -Uri "$spiroBase/spiroQuoteLinks($quoteId)" `
    -Token $bcToken `
    -Body ([ordered]@{ spiroOwner = $SentinelOwner }) `
    -IfMatch '*' | Out-Null

$verified = Get-QuoteLink -SpiroBase $spiroBase -Token $bcToken
if ([string]$verified.status -ne [string]$currentQuote.status) {
    throw 'Quote status changed unexpectedly during test preparation.'
}
if ([string]$verified.spiroOpportunityId -ne [string]$currentQuote.spiroOpportunityId) {
    throw 'Spiro opportunity ID changed unexpectedly during test preparation.'
}
if ([string]$verified.spiroOwner -ne $SentinelOwner) {
    throw 'Test sentinel owner was not written successfully.'
}

Write-Section 'TEST PREPARED'
Write-Host "Quote             : $($verified.quoteNo) | $($verified.status)" -ForegroundColor Green
Write-Host "Spiro opportunity : $($verified.spiroOpportunityName) [$($verified.spiroOpportunityId)]"
Write-Host "Temporary owner   : $($verified.spiroOwner)" -ForegroundColor Yellow
Write-Host ''
Write-Host 'Next run the repeatable sync engine for Quote 55 without -Apply.' -ForegroundColor Cyan
Write-Host 'Expected dry-run change: Owner from GPI SYNC WRITE TEST back to the live Spiro owner.' -ForegroundColor Cyan
Write-Host "Emergency rollback: rerun this script with -Restore. State file: $StatePath" -ForegroundColor Cyan
