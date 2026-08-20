[CmdletBinding()]
param(
    [string]$TenantId = "c7b2de14-71d9-4c49-a0b9-2bec103a6fdc",
    [string]$ClientId = "6ac62e44-8968-4ad9-b781-434507a5c83a",
    [string]$EnvironmentName = "Sandbox_NoZetadocs_UAT",
    [string]$CompanyName = "Gamer Packaging",
    [string]$KeyVaultName = "kv-gbca-bacf30f9",
    [int]$QuoteEntryNo = 55,
    [int]$TimeoutSeconds = 30
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-BcRequest {
    param(
        [Parameter(Mandatory)][ValidateSet('GET','POST')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token,
        [AllowNull()]$Body,
        [int]$TimeoutSec = 30
    )

    $headers = @{
        Authorization = "Bearer $Token"
        Accept = 'application/json'
    }

    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -TimeoutSec $TimeoutSec
    }

    $json = $Body | ConvertTo-Json -Depth 10 -Compress
    return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $headers -ContentType 'application/json' -Body $json -TimeoutSec $TimeoutSec
}

Write-Host ''
Write-Host 'GPI QUOTE EVALUATE DIAGNOSTIC' -ForegroundColor Cyan
Write-Host "Environment : $EnvironmentName"
Write-Host "Quote       : $QuoteEntryNo"
Write-Host "Timeout     : $TimeoutSeconds seconds"
Write-Host ''

if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "This diagnostic is restricted to Sandbox_NoZetadocs_UAT. Requested environment: $EnvironmentName"
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI (az) is required.'
}

$accountJson = & az account show --output json --only-show-errors 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($accountJson | Out-String))) {
    & az login --tenant $TenantId --only-show-errors | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Azure login failed.'
    }
}

$secret = (& az keyvault secret show --vault-name $KeyVaultName --name 'bc-client-secret' --query value --output tsv --only-show-errors).Trim()
if ([string]::IsNullOrWhiteSpace($secret)) {
    throw "Could not retrieve bc-client-secret from Key Vault $KeyVaultName."
}

try {
    $tokenResponse = Invoke-RestMethod -Method POST -Uri "https://login.microsoftonline.com/$TenantId/oauth2/v2.0/token" -ContentType 'application/x-www-form-urlencoded' -Body @{
        grant_type = 'client_credentials'
        client_id = $ClientId
        client_secret = $secret
        scope = 'https://api.businesscentral.dynamics.com/.default'
    }
}
finally {
    $secret = $null
}

$token = [string]$tokenResponse.access_token
if ([string]::IsNullOrWhiteSpace($token)) {
    throw 'Microsoft identity platform did not return an access token.'
}

$bcBase = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$EnvironmentName"
$companies = Invoke-BcRequest -Method GET -Uri "$bcBase/api/v2.0/companies" -Token $token -Body $null -TimeoutSec $TimeoutSeconds
$company = @($companies.value | Where-Object { $_.name -eq $CompanyName }) | Select-Object -First 1
if (-not $company) {
    throw "Company '$CompanyName' was not returned by the Business Central API."
}

$companyId = [string]$company.id
$quoteBase = "$bcBase/api/gpi/packagingQuotes/v1.0/companies($companyId)"

$filter = [uri]::EscapeDataString("entryNo eq $QuoteEntryNo")
$quotes = Invoke-BcRequest -Method GET -Uri "$quoteBase/packagingQuotes?`$filter=$filter" -Token $token -Body $null -TimeoutSec $TimeoutSeconds
$quote = @($quotes.value) | Select-Object -First 1
if (-not $quote) {
    throw "Quote $QuoteEntryNo was not returned by the Packaging Quotes API."
}

$quoteId = [string]$quote.id
Write-Host "Quote API ID : $quoteId"
Write-Host "Status       : $($quote.status)"
Write-Host "Customer     : $($quote.customerNo)"
Write-Host ''

$lineFilter = [uri]::EscapeDataString("quoteEntryNo eq $QuoteEntryNo")
$linesBefore = Invoke-BcRequest -Method GET -Uri "$quoteBase/packagingQuoteLines?`$filter=$lineFilter" -Token $token -Body $null -TimeoutSec $TimeoutSeconds
Write-Host 'BEFORE EVALUATE' -ForegroundColor Cyan
@($linesBefore.value) | Select-Object lineNo, productNo, uomCode, quantity, landedCostPerUnit, proposedSellPrice, targetGrossMarginPct, guardrailStatus, needsApproval | Format-Table -AutoSize

$actionUri = "$quoteBase/packagingQuotes($quoteId)/Microsoft.NAV.evaluate"
Write-Host ''
Write-Host "Calling bound action: Microsoft.NAV.evaluate" -ForegroundColor Yellow
$sw = [System.Diagnostics.Stopwatch]::StartNew()

try {
    $null = Invoke-BcRequest -Method POST -Uri $actionUri -Token $token -Body @{} -TimeoutSec $TimeoutSeconds
    $sw.Stop()
    Write-Host "Evaluate returned in $([math]::Round($sw.Elapsed.TotalSeconds, 2)) seconds." -ForegroundColor Green
}
catch {
    $sw.Stop()
    Write-Host "Evaluate failed or timed out after $([math]::Round($sw.Elapsed.TotalSeconds, 2)) seconds." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    throw
}

$quoteAfter = Invoke-BcRequest -Method GET -Uri "$quoteBase/packagingQuotes($quoteId)" -Token $token -Body $null -TimeoutSec $TimeoutSeconds
$linesAfter = Invoke-BcRequest -Method GET -Uri "$quoteBase/packagingQuoteLines?`$filter=$lineFilter" -Token $token -Body $null -TimeoutSec $TimeoutSeconds

Write-Host ''
Write-Host 'AFTER EVALUATE' -ForegroundColor Cyan
Write-Host "Last Evaluated At : $($quoteAfter.lastEvaluatedAt)"
Write-Host "Approval Lines    : $($quoteAfter.approvalLineCount)"
@($linesAfter.value) | Select-Object lineNo, productNo, uomCode, guardrailStatus, needsApproval, customerHistoryLineCount, customerHistoryMedian, customerHistoryVariancePct, guardrailMessage | Format-List

Write-Host ''
Write-Host 'DIAGNOSTIC COMPLETE' -ForegroundColor Green
Write-Host 'This invokes the same server-side quote evaluation as the page action, so a successful result confirms the AL/backend path is working.'
