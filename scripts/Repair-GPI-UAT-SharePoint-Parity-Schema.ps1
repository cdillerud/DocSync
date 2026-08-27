#requires -Version 7.0
<#
.SYNOPSIS
Guarded UAT-only remediation for the live GPI-DocumentHub-Test SharePoint metadata schema.

.DESCRIPTION
Creates only missing AP/Warehouse parity metadata columns in:
  https://gamerpackaging1.sharepoint.com/sites/GPI-DocumentHub-Test
  Documents library

Safety:
- UAT SharePoint site is hard-pinned.
- Production-like targets are rejected.
- Existing columns are never altered or deleted.
- Wrong-type existing columns fail closed.
- Requires explicit -Apply.
- Writes a rollback/evidence manifest containing only columns created by this run.

Microsoft Graph delegated permission required: Sites.Manage.All
#>

[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$TenantId = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc',
    [string]$SiteHost = 'gamerpackaging1.sharepoint.com',
    [string]$SitePath = '/sites/GPI-DocumentHub-Test',
    [string]$LibraryDisplayName = 'Documents'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $Apply) {
    throw 'Safety guard: no mutation performed. Re-run with -Apply to create missing UAT parity columns.'
}

if ($SiteHost -ne 'gamerpackaging1.sharepoint.com' -or
    $SitePath -ne '/sites/GPI-DocumentHub-Test' -or
    $LibraryDisplayName -ne 'Documents') {
    throw 'Safety guard: target must be GPI-DocumentHub-Test / Documents.'
}

$target = "$SiteHost$SitePath/$LibraryDisplayName".ToLowerInvariant()
foreach ($token in @('production','gpi-documenthub-prod','gpi-documenthub-production')) {
    if ($target.Contains($token)) {
        throw "Safety guard: Production-like SharePoint target detected: $target"
    }
}

function Section([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
}

function Ensure-MgAuthModule {
    if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.Authentication)) {
        Write-Host 'Installing Microsoft.Graph.Authentication for CurrentUser...' -ForegroundColor Yellow
        Install-Module Microsoft.Graph.Authentication -Scope CurrentUser -Force -AllowClobber -Repository PSGallery
    }
    Import-Module Microsoft.Graph.Authentication -ErrorAction Stop
}

function Invoke-GraphJson {
    param(
        [Parameter(Mandatory)][ValidateSet('GET','POST')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [object]$Body
    )

    if ($Method -eq 'GET') {
        return Invoke-MgGraphRequest -Method GET -Uri $Uri -OutputType PSObject
    }

    $json = $Body | ConvertTo-Json -Depth 10
    return Invoke-MgGraphRequest -Method POST -Uri $Uri -Body $json -ContentType 'application/json' -OutputType PSObject
}

function Get-ColumnKind {
    param([Parameter(Mandatory)]$Column)
    foreach ($kind in @('boolean','calculated','choice','currency','dateTime','geolocation','lookup','number','personOrGroup','text','hyperlinkOrPicture')) {
        if ($null -ne $Column.PSObject.Properties[$kind] -and $null -ne $Column.$kind) {
            return $kind
        }
    }
    return 'unknown'
}

function New-ColumnBody {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][ValidateSet('text','number','boolean')][string]$Kind,
        [switch]$LongText
    )

    $body = [ordered]@{
        name                = $Name
        displayName         = $Name
        description         = 'GPI AP/Warehouse Square9 parity metadata'
        required            = $false
        hidden              = $false
        indexed             = $false
        enforceUniqueValues = $false
    }

    switch ($Kind) {
        'text' {
            if ($LongText) {
                $body.text = @{
                    allowMultipleLines = $true
                    appendChangesToExistingText = $false
                    linesForEditing = 4
                }
            }
            else {
                $body.text = @{
                    allowMultipleLines = $false
                    appendChangesToExistingText = $false
                    linesForEditing = 0
                    maxLength = 255
                }
            }
        }
        'number' {
            $body.number = @{}
        }
        'boolean' {
            $body.boolean = @{}
        }
    }

    return $body
}

$expected = [ordered]@{
    'GPI_SourceTableID'       = @{ Kind='number';  Long=$false }
    'GPI_SourceSystemId'      = @{ Kind='text';    Long=$false }
    'GPI_SourceDocumentType'  = @{ Kind='text';    Long=$false }
    'GPI_SourceDocumentNo'    = @{ Kind='text';    Long=$false }
    'GPI_SourcePartyType'     = @{ Kind='text';    Long=$false }
    'GPI_SourcePartyNo'       = @{ Kind='text';    Long=$false }
    'GPI_OriginalFileName'    = @{ Kind='text';    Long=$false }
    'GPI_SharePointFileName'  = @{ Kind='text';    Long=$false }
    'GPI_SharePointPath'      = @{ Kind='text';    Long=$true  }
    'GPI_SharePointURL'       = @{ Kind='text';    Long=$true  }
    'GPI_Status'              = @{ Kind='text';    Long=$false }
    'GPI_MatchStatus'         = @{ Kind='text';    Long=$false }
    'GPI_MatchMethod'         = @{ Kind='text';    Long=$false }
    'GPI_MatchConfidence'     = @{ Kind='number';  Long=$false }
    'GPI_Candidates'          = @{ Kind='text';    Long=$true  }
    'ImportReady'             = @{ Kind='boolean'; Long=$false }
}

Section '1. HARD SAFETY / GRAPH AUTH'
Ensure-MgAuthModule

$ctx = Get-MgContext -ErrorAction SilentlyContinue
$needLogin = $true
if ($ctx) {
    $scopeSet = @($ctx.Scopes)
    if ($ctx.TenantId -eq $TenantId -and $scopeSet -contains 'Sites.Manage.All') {
        $needLogin = $false
    }
}
if ($needLogin) {
    Disconnect-MgGraph -ErrorAction SilentlyContinue | Out-Null
    Connect-MgGraph -TenantId $TenantId -Scopes 'Sites.Manage.All' -NoWelcome
}

$ctx = Get-MgContext
if ($ctx.TenantId -ne $TenantId -or @($ctx.Scopes) -notcontains 'Sites.Manage.All') {
    throw 'PARITY BLOCKER: Microsoft Graph Sites.Manage.All delegated permission was not granted.'
}
Write-Host "Tenant     : $($ctx.TenantId)" -ForegroundColor Green
Write-Host 'Permission : Sites.Manage.All' -ForegroundColor Green
Write-Host 'Production : HARD BLOCKED' -ForegroundColor Green

Section '2. RESOLVE EXACT UAT SITE / LIBRARY'
$siteUri = 'https://graph.microsoft.com/v1.0/sites/' + $SiteHost + ':' + $SitePath + '?$select=id,displayName,webUrl'
$site = Invoke-GraphJson -Method GET -Uri $siteUri
if ($site.displayName -ne 'GPI-DocumentHub-Test') {
    throw "PARITY BLOCKER: unexpected site '$($site.displayName)'."
}

$listsUri = 'https://graph.microsoft.com/v1.0/sites/' + $site.id + '/lists?$select=id,displayName,webUrl,list'
$lists = Invoke-GraphJson -Method GET -Uri $listsUri
$library = @($lists.value | Where-Object {
    $_.displayName -eq $LibraryDisplayName -and $_.list.template -eq 'documentLibrary'
})
if ($library.Count -ne 1) {
    throw "PARITY BLOCKER: expected exactly one Documents document library, found $($library.Count)."
}
$library = $library[0]

Write-Host "Site    : $($site.displayName)" -ForegroundColor Green
Write-Host "URL     : $($site.webUrl)" -ForegroundColor Green
Write-Host "Library : $($library.displayName)" -ForegroundColor Green

Section '3. PRE-WRITE CONTRACT CHECK'
$columnsUri = 'https://graph.microsoft.com/v1.0/sites/' + $site.id + '/lists/' + $library.id + '/columns?$select=id,name,displayName,hidden,readOnly,boolean,number,text'
$current = @( (Invoke-GraphJson -Method GET -Uri $columnsUri).value )

$toCreate = [System.Collections.Generic.List[string]]::new()
$wrongType = [System.Collections.Generic.List[string]]::new()

foreach ($name in $expected.Keys) {
    $match = @($current | Where-Object { $_.name -eq $name })
    if ($match.Count -eq 0) {
        $toCreate.Add($name)
        continue
    }
    if ($match.Count -gt 1) {
        throw "PARITY BLOCKER: duplicate internal column '$name'."
    }
    $kind = Get-ColumnKind $match[0]
    if ($kind -ne $expected[$name].Kind) {
        $wrongType.Add("$name expected '$($expected[$name].Kind)' but found '$kind'")
    }
}

if ($wrongType.Count -gt 0) {
    $wrongType | ForEach-Object { Write-Host "BLOCKER $_" -ForegroundColor Red }
    throw 'PARITY BLOCKER: existing wrong-type columns are not safe to alter automatically.'
}

Write-Host "Missing columns to create : $($toCreate.Count)"
if ($toCreate.Count -eq 0) {
    Write-Host 'No schema changes required.' -ForegroundColor Green
}

Section '4. CREATE ONLY MISSING UAT COLUMNS'
$created = [System.Collections.Generic.List[object]]::new()

foreach ($name in $toCreate) {
    $spec = $expected[$name]
    $body = New-ColumnBody -Name $name -Kind $spec.Kind -LongText:([bool]$spec.Long)

    try {
        $result = Invoke-GraphJson -Method POST -Uri (
            'https://graph.microsoft.com/v1.0/sites/' + $site.id + '/lists/' + $library.id + '/columns'
        ) -Body $body
    }
    catch {
        Write-Host "FAILED $name" -ForegroundColor Red
        throw
    }

    $actualKind = Get-ColumnKind $result
    if ($result.name -ne $name -or $actualKind -ne $spec.Kind) {
        throw "PARITY BLOCKER: Graph created unexpected column contract for '$name' (name='$($result.name)', kind='$actualKind')."
    }

    $created.Add([pscustomobject]@{
        Name = [string]$result.name
        Id   = [string]$result.id
        Kind = $actualKind
    })

    Write-Host "CREATED $name [$actualKind]" -ForegroundColor Green
}

Section '5. POST-WRITE LIVE VERIFICATION'
$verifiedColumns = @( (Invoke-GraphJson -Method GET -Uri $columnsUri).value )
$results = [System.Collections.Generic.List[object]]::new()
$blockers = [System.Collections.Generic.List[string]]::new()

foreach ($name in $expected.Keys) {
    $match = @($verifiedColumns | Where-Object { $_.name -eq $name })
    if ($match.Count -ne 1) {
        $results.Add([pscustomobject]@{
            InternalName=$name; ExpectedKind=$expected[$name].Kind; ActualKind=''; Status='MISSING'
        })
        $blockers.Add("Expected one '$name', found $($match.Count)")
        continue
    }

    $kind = Get-ColumnKind $match[0]
    $status = if ($kind -eq $expected[$name].Kind) { 'PASS' } else { 'TYPE MISMATCH' }
    $results.Add([pscustomobject]@{
        InternalName=$name; ExpectedKind=$expected[$name].Kind; ActualKind=$kind; Status=$status
    })
    if ($status -ne 'PASS') {
        $blockers.Add("$name expected '$($expected[$name].Kind)' but found '$kind'")
    }
}

$results | Format-Table -AutoSize

$repoRoot = 'C:\Users\ChadDillerud\Documents\DocSync-Zetadocs'
$evidenceRoot = Join-Path $repoRoot '.gpi-diagnostics\sharepoint-parity-schema-remediation'
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

$resultsPath = Join-Path $evidenceRoot "GPI-DocumentHub-Test-Schema-Verification-$stamp.csv"
$createdPath = Join-Path $evidenceRoot "GPI-DocumentHub-Test-Created-Columns-$stamp.csv"
$results | Export-Csv -LiteralPath $resultsPath -NoTypeInformation -Encoding utf8
$created | Export-Csv -LiteralPath $createdPath -NoTypeInformation -Encoding utf8

Section '6. RESULT'
Write-Host "Verification evidence : $resultsPath"
Write-Host "Created-column manifest: $createdPath"
Write-Host "Columns created        : $($created.Count)"

if ($blockers.Count -gt 0) {
    Write-Host 'PARITY BLOCKER - UAT SHAREPOINT SCHEMA REMAINS INVALID' -ForegroundColor Red
    $blockers | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
    exit 1
}

Write-Host 'VALIDATED PARITY - UAT SHAREPOINT SCHEMA CONTRACT PASS' -ForegroundColor Green
Write-Host "Required columns validated: $($expected.Count)" -ForegroundColor Green
Write-Host 'Existing columns were not altered or deleted.' -ForegroundColor Green
Write-Host 'Production was not touched.' -ForegroundColor Green
exit 0
