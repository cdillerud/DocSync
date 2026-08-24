[CmdletBinding()]
param(
    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step {
    param([Parameter(Mandatory)][string]$Text)
    Write-Host "`n== $Text ==" -ForegroundColor Cyan
}

function Replace-Once {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Label
    )

    $first = $Text.IndexOf($Old, [System.StringComparison]::Ordinal)
    if ($first -lt 0) { throw "0.21 patch anchor not found: $Label" }
    $second = $Text.IndexOf($Old, $first + $Old.Length, [System.StringComparison]::Ordinal)
    if ($second -ge 0) { throw "0.21 patch anchor is not unique: $Label" }

    return $Text.Substring(0, $first) + $New + $Text.Substring($first + $Old.Length)
}

function Save-PatchedFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $backup = "$Path.pre-0.21.bak"
    if (-not (Test-Path -LiteralPath $backup)) {
        Copy-Item -LiteralPath $Path -Destination $backup -Force
    }

    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Patched: $Path" -ForegroundColor DarkGreen
}

$appJson = Join-Path $ProjectPath 'app.json'
$quoteTable = Join-Path $ProjectPath 'src\TableExtensions\GPISpiroQuote.TableExt.al'
$quoteCard = Join-Path $ProjectPath 'src\PageExtensions\GPISpiroQuoteCard.PageExt.al'
$quoteApi = Join-Path $ProjectPath 'src\Pages\GPISpiroQuoteAPI.Page.al'
$preflight = Join-Path $ProjectPath 'scripts\Test-GPISpiroQuoteWritebackUAT.ps1'

foreach ($file in @($appJson, $quoteTable, $quoteCard, $quoteApi)) {
    if (-not (Test-Path -LiteralPath $file)) { throw "Required file not found: $file" }
}

Write-Step 'PRECHECK 0.20'
$app = Get-Content -LiteralPath $appJson -Raw | ConvertFrom-Json
if ([string]$app.version -ne '0.20.0.0') {
    throw "Expected local app version 0.20.0.0 before the 0.21 upgrade. Found $($app.version)."
}

$tableRaw = Get-Content -LiteralPath $quoteTable -Raw
$cardRaw = Get-Content -LiteralPath $quoteCard -Raw
$apiRaw = Get-Content -LiteralPath $quoteApi -Raw

foreach ($marker in @('GPI Spiro Rating', 'Refresh Spiro Context', 'Unlink Spiro Opportunity', 'spiroCloseDate')) {
    if (-not ($tableRaw.Contains($marker) -or $cardRaw.Contains($marker) -or $apiRaw.Contains($marker))) {
        throw "Expected 0.20 marker not found in local source: $marker"
    }
}

if ($tableRaw.Contains('GPI Spiro Push Status')) {
    throw '0.21 writeback foundation already appears to be present.'
}

Write-Host '0.20 source precheck passed.' -ForegroundColor Green

Write-Step 'BUMP APP VERSION TO 0.21.0.0'
$appText = Get-Content -LiteralPath $appJson -Raw
$appText = Replace-Once -Text $appText -Old '"version": "0.20.0.0"' -New '"version": "0.21.0.0"' -Label 'app version'
Save-PatchedFile -Path $appJson -Content $appText

Write-Step 'ADD SPIRO WRITEBACK TRACKING FIELDS TO QUOTE'
$text = Get-Content -LiteralPath $quoteTable -Raw
$anchor = @'
        field(71135; "GPI Spiro Rating"; Text[50])
        {
            Caption = 'Spiro Rating';
        }
'@
$replacement = $anchor + @'
        field(71136; "GPI Spiro Push Status"; Text[30])
        {
            Caption = 'Spiro Push Status';
        }
        field(71137; "GPI Spiro Last Pushed At"; DateTime)
        {
            Caption = 'Spiro Last Pushed At';
        }
        field(71138; "GPI Spiro Last Pushed By"; Text[100])
        {
            Caption = 'Spiro Last Pushed By';
        }
        field(71139; "GPI Spiro Push Message"; Text[250])
        {
            Caption = 'Spiro Push Message';
        }
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'Spiro Rating field'
Save-PatchedFile -Path $quoteTable -Content $text

Write-Step 'SHOW WRITEBACK STATUS ON QUOTE CARD'
$text = Get-Content -LiteralPath $quoteCard -Raw
$anchor = @'
                field("GPI Spiro Rating"; Rec."GPI Spiro Rating")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
'@
$replacement = $anchor + @'
                field("GPI Spiro Push Status"; Rec."GPI Spiro Push Status")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Last Pushed At"; Rec."GPI Spiro Last Pushed At")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Push Message"; Rec."GPI Spiro Push Message")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'quote card Spiro Rating field'
Save-PatchedFile -Path $quoteCard -Content $text

Write-Step 'EXPOSE WRITEBACK TRACKING THROUGH QUOTE LINK API'
$text = Get-Content -LiteralPath $quoteApi -Raw
$anchor = @'
                field(spiroRating; Rec."GPI Spiro Rating")
                {
                    Caption = 'Spiro Rating';
                    Editable = false;
                }
'@
$replacement = $anchor + @'
                field(spiroPushStatus; Rec."GPI Spiro Push Status")
                {
                    Caption = 'Spiro Push Status';
                }
                field(spiroLastPushedAt; Rec."GPI Spiro Last Pushed At")
                {
                    Caption = 'Spiro Last Pushed At';
                }
                field(spiroLastPushedBy; Rec."GPI Spiro Last Pushed By")
                {
                    Caption = 'Spiro Last Pushed By';
                }
                field(spiroPushMessage; Rec."GPI Spiro Push Message")
                {
                    Caption = 'Spiro Push Message';
                }
'@
$text = Replace-Once -Text $text -Old $anchor -New $replacement -Label 'quote API Spiro Rating field'
Save-PatchedFile -Path $quoteApi -Content $text

Write-Step 'CREATE READ-ONLY SPIRO WRITEBACK PREFLIGHT'
$script = @'
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
'@

[System.IO.File]::WriteAllText($preflight, $script, [System.Text.UTF8Encoding]::new($false))
Write-Host "Created: $preflight" -ForegroundColor DarkGreen

Write-Step 'VALIDATE 0.21 PATCH'
$checks = @(
    @{ Path = $appJson; Pattern = '"version": "0.21.0.0"'; Label = '0.21 app version' },
    @{ Path = $quoteTable; Pattern = '71136; "GPI Spiro Push Status"'; Label = 'quote push status field' },
    @{ Path = $quoteTable; Pattern = '71139; "GPI Spiro Push Message"'; Label = 'quote push message field' },
    @{ Path = $quoteCard; Pattern = 'GPI Spiro Last Pushed At'; Label = 'quote card push timestamp' },
    @{ Path = $quoteApi; Pattern = 'field\(spiroPushStatus;'; Label = 'quote API push status' },
    @{ Path = $quoteApi; Pattern = 'field\(spiroPushMessage;'; Label = 'quote API push message' },
    @{ Path = $preflight; Pattern = 'READ ONLY'; Label = 'read-only writeback preflight' },
    @{ Path = $preflight; Pattern = 'bc_packaging_quote'; Label = 'dedicated quote-link target discovery' }
)

foreach ($check in $checks) {
    $raw = Get-Content -LiteralPath $check.Path -Raw
    if ($raw -notmatch $check.Pattern) { throw "Validation failed: $($check.Label)" }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
}

Write-Host "`n0.21 Spiro quote writeback foundation patch applied successfully." -ForegroundColor Green
Write-Host 'No outbound Spiro write was introduced.' -ForegroundColor Green
Write-Host 'Next: build 0.21, publish to UAT, re-link Quote 55 if needed, then run the read-only writeback preflight.' -ForegroundColor Cyan
