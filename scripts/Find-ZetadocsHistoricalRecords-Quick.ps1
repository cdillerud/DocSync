<#
.SYNOPSIS
    Quickly finds a small sample of historical Zetadocs documents without recursively scanning every folder.

.DESCRIPTION
    Read-only. Uses Microsoft Graph drive search against SharePoint libraries named Zetadocs*.
    Stops as soon as the requested number of files is found. Intended for pre/post uninstall UAT sampling,
    not a complete historical inventory.
#>

[CmdletBinding()]
param(
    [string]$TenantId = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc',
    [string]$SiteUrl = 'https://gamerpackaging1.sharepoint.com/sites/DocsNAV',
    [ValidateRange(1,200)]
    [int]$MaxFiles = 20,
    [string]$OutputFolder = (Join-Path $env:USERPROFILE ('Desktop\Zetadocs-Quick-Sample-' + (Get-Date -Format 'yyyyMMdd-HHmmss')))
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Get-PropertyValue {
    param([object]$Object, [string]$Name)

    if ($null -eq $Object) { return $null }

    if ($Object -is [System.Collections.IDictionary]) {
        foreach ($key in $Object.Keys) {
            if ([string]$key -ieq $Name) { return $Object[$key] }
        }
        return $null
    }

    $property = $Object.PSObject.Properties |
        Where-Object { $_.Name -ieq $Name } |
        Select-Object -First 1

    if ($null -eq $property) { return $null }
    return $property.Value
}

function Invoke-GraphGet {
    param([Parameter(Mandatory)][string]$Uri)

    return Invoke-MgGraphRequest `
        -Method GET `
        -Uri $Uri `
        -OutputType PSObject `
        -ErrorAction Stop
}

function Get-GraphValues {
    param([Parameter(Mandatory)][object]$Response)

    $value = Get-PropertyValue -Object $Response -Name 'value'
    if ($null -eq $value) { return @() }
    return @($value)
}

function Clean-RecordNumber {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }

    $result = $Value.Trim()
    $result = $result -replace '\.(pdf|docx?|xlsx?|csv|txt|msg|eml|tiff?|png|jpe?g)$', ''
    $result = $result.Trim(' ', '-', '_', ':', '#', '.', ',', '(', ')', '[', ']')

    if ($result.Length -gt 50) { return '' }
    return $result
}

function Get-RecordCandidate {
    param([string]$FileName)

    $name = [System.IO.Path]::GetFileNameWithoutExtension($FileName)

    $rules = @(
        @{ Type = 'Sales Order'; Pattern = '(?i)\bpre[- ]?payment\b.*?\border\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)' },
        @{ Type = 'Sales Order'; Pattern = '(?i)\bpick[- ]?ticket\b.*?\border\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)' },
        @{ Type = 'Sales Order'; Pattern = '(?i)\bsales[- ]?order(?:[- ]?confirmation)?\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)' },
        @{ Type = 'Purchase Order'; Pattern = '(?i)\bpurchase[- ]?order(?:[- ]?warehouse)?\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)' },
        @{ Type = 'Purchase Order'; Pattern = '(?i)\bPO[\s_:#-]*(?<no>[A-Z][A-Z0-9._/-]*\d[A-Z0-9._/-]*|\d{4,})\b' },
        @{ Type = 'Transfer Order'; Pattern = '(?i)\btransfer\b.*?\b(?<no>(?:TR[\s_-]*)?[A-Z0-9]*\d{4,}[A-Z0-9._/-]*)\b' },
        @{ Type = 'Sales Return Order'; Pattern = '(?i)\b(?:sales[- ]?)?return\b.*?\border\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)' },
        @{ Type = 'Purchase Return Order'; Pattern = '(?i)\bpurchase[- ]?return\b.*?\border\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)' },
        @{ Type = 'Invoice'; Pattern = '(?i)\binvoice\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)' },
        @{ Type = 'Credit Memo'; Pattern = '(?i)\bcredit[- ]?memo\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)' },
        @{ Type = 'Order'; Pattern = '(?i)\border\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)' }
    )

    foreach ($rule in $rules) {
        if ($name -match $rule.Pattern) {
            $recordNo = Clean-RecordNumber -Value $Matches.no
            if ($recordNo) {
                return [pscustomobject]@{
                    RecordType = $rule.Type
                    RecordNo   = $recordNo
                }
            }
        }
    }

    return $null
}

if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.Authentication)) {
    Write-Host '[INFO] Installing Microsoft.Graph.Authentication for the current user...'
    Install-Module Microsoft.Graph.Authentication -Scope CurrentUser -Force -AllowClobber
}
Import-Module Microsoft.Graph.Authentication -ErrorAction Stop

$requiredScopes = @('Sites.Read.All', 'Files.Read.All')
$context = Get-MgContext -ErrorAction SilentlyContinue
$needsConnection = $true

if ($context -and $context.TenantId -eq $TenantId) {
    $needsConnection = $false
    foreach ($scope in $requiredScopes) {
        if ($context.Scopes -notcontains $scope) { $needsConnection = $true }
    }
}

if ($needsConnection) {
    Write-Host '[AUTH] Sign in with an account that can read the DocsNAV SharePoint site.'
    Connect-MgGraph -TenantId $TenantId -Scopes $requiredScopes -ContextScope Process -NoWelcome
}

New-Item -ItemType Directory -Path $OutputFolder -Force | Out-Null

$siteUri = [System.Uri]$SiteUrl
$sitePath = $siteUri.AbsolutePath.TrimEnd('/')
$siteLookupUri = 'https://graph.microsoft.com/v1.0/sites/{0}:{1}' -f $siteUri.Host, $sitePath
$site = Invoke-GraphGet -Uri $siteLookupUri
$siteId = [string](Get-PropertyValue -Object $site -Name 'id')

if ([string]::IsNullOrWhiteSpace($siteId)) {
    throw "Could not resolve SharePoint site $SiteUrl"
}

$driveResponse = Invoke-GraphGet -Uri "https://graph.microsoft.com/v1.0/sites/$siteId/drives?`$select=id,name,webUrl"
$drives = @(
    Get-GraphValues -Response $driveResponse |
    Where-Object {
        $name = [string](Get-PropertyValue -Object $_ -Name 'name')
        $name -like 'Zetadocs*'
    } |
    Sort-Object {
        $name = [string](Get-PropertyValue -Object $_ -Name 'name')
        if ($name -eq 'Zetadocs') { '0000' } else { $name }
    }
)

if ($drives.Count -eq 0) {
    throw 'No SharePoint document libraries named Zetadocs* were found.'
}

Write-Host ''
Write-Host '============================================================'
Write-Host ' Zetadocs Quick Historical Sample'
Write-Host '============================================================'
Write-Host "Target files: $MaxFiles"
Write-Host 'This uses SharePoint search and does not recursively scan every folder.'
Write-Host ''

$searchTerms = @(
    'Order',
    'Invoice',
    'Pick Ticket',
    'Pre-Payment',
    'Purchase',
    'Credit Memo',
    'Return',
    'Transfer',
    'pdf'
)

$results = [System.Collections.Generic.List[object]]::new()
$seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

foreach ($drive in $drives) {
    if ($results.Count -ge $MaxFiles) { break }

    $driveId = [string](Get-PropertyValue -Object $drive -Name 'id')
    $libraryName = [string](Get-PropertyValue -Object $drive -Name 'name')

    if ([string]::IsNullOrWhiteSpace($driveId)) { continue }

    foreach ($term in $searchTerms) {
        if ($results.Count -ge $MaxFiles) { break }

        Write-Host "[SEARCH] $libraryName : $term"

        $escapedTerm = $term.Replace("'", "''")
        $top = [Math]::Min(50, [Math]::Max(20, $MaxFiles - $results.Count))
        $searchUri = "https://graph.microsoft.com/v1.0/drives/$driveId/root/search(q='$escapedTerm')?`$top=$top&`$select=id,name,size,webUrl,createdDateTime,lastModifiedDateTime,file,parentReference"

        try {
            $response = Invoke-GraphGet -Uri $searchUri
        }
        catch {
            Write-Warning "Search failed for $libraryName / $term. $($_.Exception.Message)"
            continue
        }

        foreach ($item in (Get-GraphValues -Response $response)) {
            if ($results.Count -ge $MaxFiles) { break }

            $fileFacet = Get-PropertyValue -Object $item -Name 'file'
            if ($null -eq $fileFacet) { continue }

            $itemId = [string](Get-PropertyValue -Object $item -Name 'id')
            $fileName = [string](Get-PropertyValue -Object $item -Name 'name')

            if ([string]::IsNullOrWhiteSpace($itemId) -or [string]::IsNullOrWhiteSpace($fileName)) {
                continue
            }

            $key = "$driveId|$itemId"
            if (-not $seen.Add($key)) { continue }

            $parentReference = Get-PropertyValue -Object $item -Name 'parentReference'
            $parentPath = [string](Get-PropertyValue -Object $parentReference -Name 'path')
            $size = Get-PropertyValue -Object $item -Name 'size'
            $created = [string](Get-PropertyValue -Object $item -Name 'createdDateTime')
            $modified = [string](Get-PropertyValue -Object $item -Name 'lastModifiedDateTime')
            $webUrl = [string](Get-PropertyValue -Object $item -Name 'webUrl')
            $candidate = Get-RecordCandidate -FileName $fileName

            $recordType = ''
            $recordNo = ''
            if ($candidate) {
                $recordType = $candidate.RecordType
                $recordNo = $candidate.RecordNo
            }

            $results.Add([pscustomobject]@{
                LibraryName        = $libraryName
                FileName           = $fileName
                CandidateRecordType = $recordType
                CandidateRecordNo  = $recordNo
                ParentPath         = $parentPath
                SizeBytes          = if ($null -eq $size) { 0 } else { [Int64]$size }
                CreatedDateTime    = $created
                LastModifiedDateTime = $modified
                SharePointUrl      = $webUrl
            })

            Write-Host "[FOUND] $($results.Count)/$MaxFiles - $fileName"
        }
    }
}

if ($results.Count -eq 0) {
    throw 'No historical Zetadocs files were returned by SharePoint search.'
}

$allPath = Join-Path $OutputFolder 'Zetadocs-Quick-Sample-Files.csv'
$recordsPath = Join-Path $OutputFolder 'Zetadocs-Quick-Sample-Records.csv'
$summaryPath = Join-Path $OutputFolder 'Zetadocs-Quick-Sample-Summary.txt'

$results |
    Export-Csv -Path $allPath -NoTypeInformation -Encoding UTF8

$recordRows = @(
    $results |
    Where-Object { $_.CandidateRecordNo } |
    Group-Object CandidateRecordType, CandidateRecordNo |
    ForEach-Object {
        $first = $_.Group[0]
        [pscustomobject]@{
            RecordType = $first.CandidateRecordType
            RecordNo = $first.CandidateRecordNo
            DocumentCount = $_.Count
            ExampleFileName = $first.FileName
            LibraryName = $first.LibraryName
            SharePointUrl = $first.SharePointUrl
        }
    }
)

$recordRows |
    Export-Csv -Path $recordsPath -NoTypeInformation -Encoding UTF8

@"
Zetadocs Quick Historical Sample
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

Files found: $($results.Count)
Likely Business Central records found: $($recordRows.Count)

Files report:
$allPath

Records report:
$recordsPath

This quick sample is not a complete historical inventory.
No SharePoint content was changed.
"@ | Set-Content -Path $summaryPath -Encoding UTF8

Write-Host ''
Write-Host '============================================================'
Write-Host ' Quick sample complete'
Write-Host '============================================================'
Write-Host "Files found: $($results.Count)"
Write-Host "Likely BC records: $($recordRows.Count)"
Write-Host ''
Write-Host "Open: $recordsPath"
Write-Host "All files: $allPath"
Write-Host ''
Write-Host 'No SharePoint content was changed.'
