[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [int]$QuoteNo,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$DecisionNote,

    [switch]$Confirmed,

    [string]$TenantId =
        'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc',

    [string]$EnvironmentName =
        'Sandbox_NoZetadocs_UAT',

    [string]$CompanyId =
        '7d84c6d5-81e2-eb11-86df-00224822baa7'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ------------------------------------------------------------------------
# HARD SAFETY BOUNDARIES
# ------------------------------------------------------------------------
if ($EnvironmentName -ne 'Sandbox_NoZetadocs_UAT') {
    throw "STOP: this decision-note writer is UAT-only. Environment received: $EnvironmentName"
}

if ($QuoteNo -eq 67) {
    throw 'STOP: Packaging Quote 67 is protected and may not be used by this utility.'
}

$DecisionNote = $DecisionNote.Trim()

if ([string]::IsNullOrWhiteSpace($DecisionNote)) {
    throw 'STOP: decision note may not be blank.'
}

if ($DecisionNote -match '[\r\n]') {
    throw 'STOP: decision note must be a single line.'
}

if (-not (Get-Command Get-AzAccessToken -ErrorAction SilentlyContinue)) {
    throw 'Get-AzAccessToken is not available. Connect with Az.Accounts first.'
}

# ------------------------------------------------------------------------
# AUTH
# ------------------------------------------------------------------------
$tokenResult =
    Get-AzAccessToken `
        -ResourceUrl 'https://api.businesscentral.dynamics.com'

if ($tokenResult.Token -is [Security.SecureString]) {
    $accessToken =
        [System.Net.NetworkCredential]::new(
            '',
            $tokenResult.Token
        ).Password
}
else {
    $accessToken =
        [string]$tokenResult.Token
}

if ([string]::IsNullOrWhiteSpace($accessToken)) {
    throw 'Business Central API token was not returned.'
}

$headers = @{
    Authorization = "Bearer $accessToken"
    Accept        = 'application/json'
}

$baseUri =
    "https://api.businesscentral.dynamics.com/v2.0/" +
    "$TenantId/$EnvironmentName/api/gpi/packagingQuotes/v1.0/" +
    "companies($CompanyId)"

$filter =
    [uri]::EscapeDataString(
        "entryNo eq $QuoteNo"
    )

$quoteUri =
    "$baseUri/packagingQuotes" +
    "?`$filter=$filter" +
    "&`$select=id,entryNo,status,decisionNote"

function Get-CurrentQuote {
    $response =
        Invoke-RestMethod `
            -Method Get `
            -Uri $quoteUri `
            -Headers $headers `
            -ErrorAction Stop

    $rows = @($response.value)

    if ($rows.Count -ne 1) {
        throw "STOP: expected one Quote $QuoteNo row; received $($rows.Count)."
    }

    return $rows[0]
}

# ------------------------------------------------------------------------
# INITIAL READ
# ------------------------------------------------------------------------
$before = Get-CurrentQuote

if ([string]$before.status -ne 'Ready') {
    throw (
        "STOP: decision notes may only be written by this utility " +
        "while the quote is Ready. Current status: $($before.status)"
    )
}

$result = [ordered]@{
    quoteNo = [int]$before.entryNo
    quoteId = [string]$before.id
    status = [string]$before.status
    previousDecisionNote = [string]$before.decisionNote
    proposedDecisionNote = $DecisionNote
    confirmed = [bool]$Confirmed
    written = $false
}

if (-not $Confirmed) {
    [pscustomobject]$result
    return
}

$etag =
    [string]$before.'@odata.etag'

if ([string]::IsNullOrWhiteSpace($etag)) {
    throw 'STOP: Business Central did not return an OData ETag.'
}

$patchUri =
    "$baseUri/packagingQuotes($($before.id))"

$patchHeaders = @{
    Authorization = "Bearer $accessToken"
    Accept        = 'application/json'
    'If-Match'    = $etag
}

$body = @{
    decisionNote = $DecisionNote
} | ConvertTo-Json

# ------------------------------------------------------------------------
# CONTROLLED WRITE
# ------------------------------------------------------------------------
Invoke-RestMethod `
    -Method Patch `
    -Uri $patchUri `
    -Headers $patchHeaders `
    -ContentType 'application/json' `
    -Body $body `
    -ErrorAction Stop |
    Out-Null

# ------------------------------------------------------------------------
# VERIFY
# ------------------------------------------------------------------------
$after = Get-CurrentQuote

if ([string]$after.status -ne 'Ready') {
    throw (
        "STOP: decision-note write unexpectedly changed quote status. " +
        "Current status: $($after.status)"
    )
}

if ([string]$after.decisionNote -ne $DecisionNote) {
    throw 'STOP: Business Central decision-note verification failed.'
}

$result.status = [string]$after.status
$result.written = $true

[pscustomobject]$result