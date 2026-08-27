#requires -Version 7.0
<#
.SYNOPSIS
Read-only hard gate for the live GPI-DocumentHub-Test SharePoint parity schema.

.DESCRIPTION
Validates the exact internal SharePoint column names and primitive Graph column
kinds required by the AP/Warehouse delivery contract. This script is intentionally
read-only and hard-pinned to the GPI-DocumentHub-Test site.

Exit codes:
  0 = PASS
  1 = PARITY BLOCKER / execution failure

No Production writes. No SharePoint mutation. No Business Central mutation.
#>

[CmdletBinding()]
param(
    [string]$TenantId = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc',
    [string]$SiteHost = 'gamerpackaging1.sharepoint.com',
    [string]$SitePath = '/sites/GPI-DocumentHub-Test',
    [string]$LibraryDisplayName = 'Documents',
    [switch]$ForceLogin
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw 'PowerShell 7+ is required.'
}

if ($SiteHost -ne 'gamerpackaging1.sharepoint.com' -or
    $SitePath -ne '/sites/GPI-DocumentHub-Test' -or
    $LibraryDisplayName -ne 'Documents') {
    throw 'Safety guard: this hard gate is pinned to gamerpackaging1.sharepoint.com/sites/GPI-DocumentHub-Test / Documents.'
}

$forbidden = @('production', '/sites/gpi-documenthub-prod', 'gpi-documenthub-production')
$targetText = "$SiteHost$SitePath/$LibraryDisplayName".ToLowerInvariant()
foreach ($token in $forbidden) {
    if ($targetText.Contains($token)) {
        throw "Safety guard: Production-like SharePoint target detected: $targetText"
    }
}

function Write-Section {
    param([Parameter(Mandatory)][string]$Title)
    Write-Host ''
    Write-Host ('=' * 116) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 116) -ForegroundColor Cyan
}

function Get-GraphToken {
    if (-not (Get-Module -ListAvailable -Name Az.Accounts)) {
        throw 'Az.Accounts is required. Install-Module Az.Accounts -Scope CurrentUser'
    }

    Import-Module Az.Accounts -ErrorAction Stop

    $ctx = Get-AzContext -ErrorAction SilentlyContinue
    if ($ForceLogin -or -not $ctx -or $ctx.Tenant.Id -ne $TenantId) {
        Connect-AzAccount -Tenant $TenantId -UseDeviceAuthentication | Out-Null
    }

    $tokenResult = Get-AzAccessToken -ResourceUrl 'https://graph.microsoft.com'
    if ($tokenResult.Token -is [System.Security.SecureString]) {
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($tokenResult.Token)
        try {
            return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        }
        finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
        }
    }

    return [string]$tokenResult.Token
}

function Invoke-GraphGet {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token
    )

    Invoke-RestMethod -Method Get -Uri $Uri -Headers @{
        Authorization = "Bearer $Token"
        Accept        = 'application/json'
    }
}

function Get-ColumnKind {
    param([Parameter(Mandatory)]$Column)

    foreach ($kind in @(
        'boolean','calculated','choice','currency','dateTime','geolocation',
        'lookup','number','personOrGroup','text','hyperlinkOrPicture'
    )) {
        if ($null -ne $Column.PSObject.Properties[$kind] -and $null -ne $Column.$kind) {
            return $kind
        }
    }

    return 'unknown'
}

Write-Section '1. AUTHENTICATE READ-ONLY TO MICROSOFT GRAPH'
$token = Get-GraphToken
if ([string]::IsNullOrWhiteSpace($token)) {
    throw 'Failed to obtain a Microsoft Graph token.'
}
Write-Host 'Graph token acquired.' -ForegroundColor Green

Write-Section '2. RESOLVE EXACT UAT SHAREPOINT SITE'
$encodedSitePath = $SitePath.TrimEnd('/')
$siteUri = "https://graph.microsoft.com/v1.0/sites/$SiteHost`:$encodedSitePath?`$select=id,displayName,webUrl"
$site = Invoke-GraphGet -Uri $siteUri -Token $token

if ($site.displayName -ne 'GPI-DocumentHub-Test') {
    throw "PARITY BLOCKER: resolved unexpected SharePoint site '$($site.displayName)'."
}
if ([string]$site.webUrl -notlike 'https://gamerpackaging1.sharepoint.com/sites/GPI-DocumentHub-Test*') {
    throw "PARITY BLOCKER: resolved unexpected SharePoint URL '$($site.webUrl)'."
}

Write-Host "Site : $($site.displayName)" -ForegroundColor Green
Write-Host "URL  : $($site.webUrl)" -ForegroundColor Green
Write-Host "ID   : $($site.id)" -ForegroundColor DarkGray

Write-Section '3. RESOLVE DOCUMENT LIBRARY'
$listsUri = "https://graph.microsoft.com/v1.0/sites/$($site.id)/lists?`$select=id,displayName,webUrl,list"
$lists = Invoke-GraphGet -Uri $listsUri -Token $token
$library = @($lists.value | Where-Object {
    $_.displayName -eq $LibraryDisplayName -and $_.list.template -eq 'documentLibrary'
})

if ($library.Count -ne 1) {
    throw "PARITY BLOCKER: expected exactly one '$LibraryDisplayName' document library, found $($library.Count)."
}
$library = $library[0]
Write-Host "Library : $($library.displayName)" -ForegroundColor Green
Write-Host "List ID : $($library.id)" -ForegroundColor DarkGray

Write-Section '4. READ LIVE COLUMN CONTRACT'
$columnsUri = "https://graph.microsoft.com/v1.0/sites/$($site.id)/lists/$($library.id)/columns?`$select=id,name,displayName,hidden,readOnly,boolean,number,text"
$columnsResponse = Invoke-GraphGet -Uri $columnsUri -Token $token
$columns = @($columnsResponse.value)

$expected = [ordered]@{
    'GPI_SourceTableID'       = 'number'
    'GPI_SourceSystemId'      = 'text'
    'GPI_SourceDocumentType'  = 'text'
    'GPI_SourceDocumentNo'    = 'text'
    'GPI_SourcePartyType'     = 'text'
    'GPI_SourcePartyNo'       = 'text'
    'GPI_OriginalFileName'    = 'text'
    'GPI_SharePointFileName'  = 'text'
    'GPI_SharePointPath'      = 'text'
    'GPI_SharePointURL'       = 'text'
    'GPI_Status'              = 'text'
    'GPI_MatchStatus'         = 'text'
    'GPI_MatchMethod'         = 'text'
    'GPI_MatchConfidence'     = 'number'
    'GPI_Candidates'          = 'text'
    'ImportReady'             = 'boolean'
}

$results = [System.Collections.Generic.List[object]]::new()
$blockers = [System.Collections.Generic.List[string]]::new()

foreach ($name in $expected.Keys) {
    $match = @($columns | Where-Object { $_.name -eq $name })
    if ($match.Count -eq 0) {
        $results.Add([pscustomobject]@{
            InternalName = $name
            ExpectedKind = $expected[$name]
            ActualKind   = ''
            DisplayName  = ''
            Status       = 'MISSING'
        })
        $blockers.Add("Missing required internal column: $name")
        continue
    }

    if ($match.Count -gt 1) {
        $blockers.Add("Duplicate internal column match: $name")
    }

    $column = $match[0]
    $kind = Get-ColumnKind -Column $column
    $status = if ($kind -eq $expected[$name]) { 'PASS' } else { 'TYPE MISMATCH' }

    $results.Add([pscustomobject]@{
        InternalName = $name
        ExpectedKind = $expected[$name]
        ActualKind   = $kind
        DisplayName  = [string]$column.displayName
        Status       = $status
    })

    if ($status -ne 'PASS') {
        $blockers.Add("$name expected '$($expected[$name])' but live Graph kind is '$kind'")
    }
}

$results | Format-Table -AutoSize

$repoRoot = Split-Path -Parent $PSScriptRoot
$reportRoot = Join-Path $repoRoot '.gpi-diagnostics\sharepoint-parity-schema'
New-Item -ItemType Directory -Force -Path $reportRoot | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$csvPath = Join-Path $reportRoot "GPI-DocumentHub-Test-SharePoint-Parity-Schema-$stamp.csv"
$results | Export-Csv -LiteralPath $csvPath -NoTypeInformation -Encoding utf8

Write-Section '5. HARD GATE RESULT'
Write-Host "Evidence : $csvPath"

if ($blockers.Count -gt 0) {
    Write-Host ''
    Write-Host 'PARITY BLOCKER - LIVE SHAREPOINT SCHEMA CONTRACT FAILED' -ForegroundColor Red
    foreach ($blocker in $blockers) {
        Write-Host " - $blocker" -ForegroundColor Red
    }
    exit 1
}

Write-Host 'VALIDATED PARITY - LIVE SHAREPOINT COLUMN CONTRACT PASS' -ForegroundColor Green
Write-Host "Required columns validated: $($expected.Count)" -ForegroundColor Green
Write-Host 'No SharePoint data or configuration was modified.' -ForegroundColor Green
exit 0
