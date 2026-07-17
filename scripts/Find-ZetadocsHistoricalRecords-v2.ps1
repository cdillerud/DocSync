<#
.SYNOPSIS
  Finds SharePoint files in the historical Zetadocs archive and produces CSV lists
  of likely Business Central records, customer/vendor folders, and unmatched files.

.DESCRIPTION
  Read-only. Uses Microsoft Graph delegated permissions Sites.Read.All and
  Files.Read.All. It does not modify, move, rename, upload, or delete anything.

  Gamer Packaging defaults:
    Site:        https://gamerpackaging1.sharepoint.com/sites/DocsNAV
    Root folder: Zetadocs

  Common archive pattern:
    Zetadocs/MM-DD-YYYY/Customer or Vendor Name/Sales or Purchase/File.pdf
#>

[CmdletBinding()]
param(
    [string]$TenantId = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc',
    [string]$SiteUrl = 'https://gamerpackaging1.sharepoint.com/sites/DocsNAV',
    [string]$LibraryName = '',
    [string]$RootFolder = 'Zetadocs',
    [string]$OutputFolder = (Join-Path $env:USERPROFILE ('Desktop\Zetadocs-Historical-Inventory-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))),
    [ValidateRange(0,10000000)]
    [int]$MaxFiles = 0,
    [ValidateRange(1,500)]
    [int]$UatSampleCount = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Section {
    param([string]$Text)
    Write-Host ''
    Write-Host ('=' * 68)
    Write-Host (' ' + $Text)
    Write-Host ('=' * 68)
}

function Ensure-GraphModule {
    if (-not (Get-Module -ListAvailable -Name Microsoft.Graph.Authentication)) {
        Write-Host '[INFO] Installing Microsoft.Graph.Authentication for the current user...'
        Install-Module Microsoft.Graph.Authentication -Scope CurrentUser -Force -AllowClobber
    }
    Import-Module Microsoft.Graph.Authentication -ErrorAction Stop
}

function Invoke-GraphGet {
    param([string]$Uri, [int]$Attempts = 6)

    $delay = 2
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            return Invoke-MgGraphRequest -Method GET -Uri $Uri -OutputType PSObject -ErrorAction Stop
        }
        catch {
            if ($i -eq $Attempts) { throw }
            Write-Warning "Graph request failed. Retrying in $delay seconds. $($_.Exception.Message)"
            Start-Sleep -Seconds $delay
            $delay = [Math]::Min($delay * 2, 32)
        }
    }
}


function Get-ObjectPropertyValue {
    param(
        [Parameter(Mandatory)][object]$Object,
        [Parameter(Mandatory)][string]$Name
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-GraphPages {
    param([string]$Uri)

    $items = [System.Collections.Generic.List[object]]::new()
    $next = $Uri

    while ($next) {
        $response = Invoke-GraphGet -Uri $next
        $pageValue = Get-ObjectPropertyValue -Object $response -Name 'value'
        if ($null -ne $pageValue) {
            foreach ($item in $pageValue) { $items.Add($item) }
        }
        else {
            $items.Add($response)
        }

        $next = ''
        $property = $response.PSObject.Properties['@odata.nextLink']
        if ($null -ne $property -and $property.Value) {
            $next = [string]$property.Value
        }
    }

    return $items
}

function Encode-GraphPath {
    param([string]$Path)
    return (($Path.Trim('/') -split '/') | ForEach-Object { [Uri]::EscapeDataString($_) }) -join '/'
}

function Clean-RecordNo {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $result = $Value.Trim()
    $result = $result -replace '\.(pdf|docx?|xlsx?|csv|txt|msg|eml|tiff?|png|jpe?g)$',''
    $result = $result.Trim(' ','-','_',':','#','.',',','(',')','[',']')
    if ($result.Length -gt 50) { return '' }
    return $result
}

function Get-PathDetails {
    param([string]$RelativePath)

    $folderPath = Split-Path $RelativePath -Parent
    $segments = @()
    if ($folderPath) { $segments = $folderPath -split '[\\/]' }

    $archiveDate = ''
    $party = ''
    $area = ''

    for ($i = 0; $i -lt $segments.Count; $i++) {
        $segment = $segments[$i]

        if (-not $archiveDate -and $segment -match '^\d{2}-\d{2}-\d{4}$') {
            $archiveDate = $segment
            if (($i + 1) -lt $segments.Count) { $party = $segments[$i + 1] }
        }

        if ($segment -match '^(?i:Sales|Purchase|Warehouse)$') {
            $area = $segment
        }
    }

    if (-not $party -and $segments.Count -ge 2) {
        $party = $segments[$segments.Count - 2]
    }

    [pscustomobject]@{
        ArchiveDate = $archiveDate
        PartyFolder = $party
        Area = $area
    }
}

function Get-RecordCandidate {
    param([string]$FileName, [string]$Area)

    $name = [IO.Path]::GetFileNameWithoutExtension($FileName)
    $rules = @(
        @{ Type='Sales Order'; Pattern='(?i)\bpre[- ]?payment\b.*?\border\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)'; Reason='Prepayment filename' },
        @{ Type='Sales Order'; Pattern='(?i)\bpick[- ]?ticket\b.*?\border\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)'; Reason='Pick ticket filename' },
        @{ Type='Sales Order'; Pattern='(?i)\bsales[- ]?order(?:[- ]?confirmation)?\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)'; Reason='Sales order filename' },
        @{ Type='Purchase Order'; Pattern='(?i)\bpurchase[- ]?order(?:[- ]?warehouse)?\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)'; Reason='Purchase order filename' },
        @{ Type='Purchase Order'; Pattern='(?i)\bwarehouse[- ]?(?:receiving|receipt)[- ]?(?:notice|notification)\b.*?\b(?:PO|Order)[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)'; Reason='Warehouse receiving filename' },
        @{ Type='Purchase Order'; Pattern='(?i)\bPO[\s_:#-]*(?<no>[A-Z][A-Z0-9._/-]*\d[A-Z0-9._/-]*|\d{4,})\b'; Reason='PO reference in filename' },
        @{ Type='Transfer Order'; Pattern='(?i)\btransfer\b.*?\b(?<no>(?:TR[\s_-]*)?[A-Z0-9]*\d{4,}[A-Z0-9._/-]*)\b'; Reason='Transfer filename' },
        @{ Type='Sales Return Order'; Pattern='(?i)\b(?:sales[- ]?)?return\b.*?\border\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)'; Reason='Sales return filename' },
        @{ Type='Purchase Return Order'; Pattern='(?i)\bpurchase[- ]?return\b.*?\border\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)'; Reason='Purchase return filename' },
        @{ Type='Invoice'; Pattern='(?i)\binvoice\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)'; Reason='Invoice filename' },
        @{ Type='Credit Memo'; Pattern='(?i)\bcredit[- ]?memo\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)'; Reason='Credit memo filename' },
        @{ Type='Order'; Pattern='(?i)\border\b[\s_:#-]*(?<no>[A-Z0-9][A-Z0-9._/-]*)'; Reason='Generic order filename' }
    )

    foreach ($rule in $rules) {
        if ($name -match $rule.Pattern) {
            $type = $rule.Type
            if ($type -eq 'Invoice') {
                $type = if ($Area -match '(?i)^Purchase$') { 'Posted Purchase Invoice' } else { 'Posted Sales Invoice' }
            }
            elseif ($type -eq 'Credit Memo') {
                $type = if ($Area -match '(?i)^Purchase$') { 'Posted Purchase Credit Memo' } else { 'Posted Sales Credit Memo' }
            }
            elseif ($type -eq 'Order') {
                $type = if ($Area -match '(?i)^Purchase$') { 'Purchase Order' } elseif ($Area -match '(?i)^Warehouse$') { 'Warehouse Record' } else { 'Sales Order' }
            }

            $number = Clean-RecordNo $Matches.no
            if ($number) {
                return [pscustomobject]@{
                    RecordType = $type
                    RecordNo = $number
                    Confidence = 'Filename match'
                    MatchReason = $rule.Reason
                }
            }
        }
    }

    return $null
}

Write-Section 'Zetadocs Historical Document Inventory'
Write-Host "Tenant:      $TenantId"
Write-Host "Site:        $SiteUrl"
Write-Host "Library pattern/root hint: $RootFolder"
Write-Host "Output:      $OutputFolder"
Write-Host ''
Write-Host 'This inventory is read-only. No SharePoint files will be changed.'

Ensure-GraphModule

$requiredScopes = @('Sites.Read.All','Files.Read.All')
$context = Get-MgContext -ErrorAction SilentlyContinue
$connect = $true
if ($context -and $context.TenantId -eq $TenantId) {
    $connect = $false
    foreach ($scope in $requiredScopes) {
        if ($context.Scopes -notcontains $scope) { $connect = $true }
    }
}

if ($connect) {
    Write-Host ''
    Write-Host '[AUTH] Sign in with an account that can read the DocsNAV SharePoint site.'
    Connect-MgGraph -TenantId $TenantId -Scopes $requiredScopes -ContextScope Process -NoWelcome
}

New-Item -ItemType Directory -Path $OutputFolder -Force | Out-Null

$siteUri = [Uri]$SiteUrl
$sitePath = $siteUri.AbsolutePath.TrimEnd('/')
$site = Invoke-GraphGet -Uri ("https://graph.microsoft.com/v1.0/sites/{0}:{1}" -f $siteUri.Host,$sitePath)
$siteId = [string]$site.id
if (-not $siteId) { throw "Could not resolve SharePoint site $SiteUrl" }

$drives = @(Get-GraphPages -Uri "https://graph.microsoft.com/v1.0/sites/$siteId/drives?`$select=id,name,webUrl,driveType")
if (-not $drives.Count) { throw "No document libraries were found at $SiteUrl" }

$scanTargets = [System.Collections.Generic.List[object]]::new()

if ($LibraryName) {
    $selectedDrives = @(
        $drives | Where-Object {
            $_.name -eq $LibraryName -or $_.name -like $LibraryName
        }
    )

    if (-not $selectedDrives.Count) {
        throw "Library '$LibraryName' not found. Available libraries: $(($drives.name | Sort-Object) -join ', ')"
    }
}
else {
    # Gamer Packaging stores historical Zetadocs content in separate document
    # libraries named Zetadocs, Zetadocs2021, Zetadocs2022, and so on.
    # Prefer those library roots instead of looking for a Zetadocs folder inside
    # another library.
    $selectedDrives = @(
        $drives | Where-Object {
            $_.name -like "$RootFolder*"
        }
    )
}

foreach ($selectedDrive in $selectedDrives) {
    $driveRoot = Invoke-GraphGet -Uri (
        "https://graph.microsoft.com/v1.0/drives/{0}/root?`$select=id,name,webUrl,folder" -f
            $selectedDrive.id
    )

    $scanTargets.Add(
        [pscustomobject]@{
            Drive = $selectedDrive
            Root = $driveRoot
            DisplayRoot = '[library root]'
        }
    )
}

# Backward-compatible fallback for tenants where Zetadocs is a folder located
# inside a differently named document library.
if (-not $scanTargets.Count) {
    $encodedRoot = Encode-GraphPath $RootFolder

    foreach ($candidateDrive in $drives) {
        try {
            $folderRoot = Invoke-MgGraphRequest `
                -Method GET `
                -Uri ("https://graph.microsoft.com/v1.0/drives/{0}/root:/{1}?`$select=id,name,webUrl,folder" -f $candidateDrive.id,$encodedRoot) `
                -OutputType PSObject `
                -ErrorAction Stop

            $rootFolderFacet = Get-ObjectPropertyValue -Object $folderRoot -Name 'folder'
            if ($null -ne $rootFolderFacet) {
                $scanTargets.Add(
                    [pscustomobject]@{
                        Drive = $candidateDrive
                        Root = $folderRoot
                        DisplayRoot = $RootFolder
                    }
                )
            }
        }
        catch {
            # A 404 here only means this library does not contain the folder.
        }
    }
}

if (-not $scanTargets.Count) {
    throw "No Zetadocs libraries or '$RootFolder' folders were found. Libraries checked: $(($drives.name | Sort-Object) -join ', ')"
}

Write-Host '[FOUND] Scan targets:'
foreach ($target in $scanTargets) {
    Write-Host ("  - Library: {0}; Start: {1}" -f $target.Drive.name,$target.DisplayRoot)
}

Write-Section 'Scanning files'
$files = [System.Collections.Generic.List[object]]::new()
$folderCount = 0
$stop = $false

foreach ($target in $scanTargets) {
    if ($stop) { break }

    $drive = $target.Drive
    $rootItem = $target.Root
    $queue = [System.Collections.Generic.Queue[object]]::new()
    $queue.Enqueue([pscustomobject]@{ Id=[string]$rootItem.id; RelativePath='' })

    while ($queue.Count -gt 0 -and -not $stop) {
        $folder = $queue.Dequeue()
        $folderCount++
        $childrenUri = "https://graph.microsoft.com/v1.0/drives/$($drive.id)/items/$($folder.Id)/children?`$select=id,name,size,webUrl,createdDateTime,lastModifiedDateTime,file,folder"
        $children = @(Get-GraphPages -Uri $childrenUri)

        foreach ($child in $children) {
            $relative = if ($folder.RelativePath) { "$($folder.RelativePath)/$($child.name)" } else { [string]$child.name }
            $childFolderFacet = Get-ObjectPropertyValue -Object $child -Name 'folder'
            $childFileFacet = Get-ObjectPropertyValue -Object $child -Name 'file'
            if ($null -ne $childFolderFacet) {
                $queue.Enqueue([pscustomobject]@{ Id=[string]$child.id; RelativePath=$relative })
                continue
            }
            if ($null -eq $childFileFacet) { continue }

            $details = Get-PathDetails -RelativePath $relative
            $candidate = Get-RecordCandidate -FileName ([string]$child.name) -Area $details.Area

            $recordType = ''
            $recordNo = ''
            $confidence = 'Unmatched'
            $reason = ''
            if ($candidate) {
                $recordType = $candidate.RecordType
                $recordNo = $candidate.RecordNo
                $confidence = $candidate.Confidence
                $reason = $candidate.MatchReason
            }

            $files.Add([pscustomobject]@{
                LibraryName = [string]$drive.name
                LibraryWebUrl = [string]$drive.webUrl
                ArchiveDate = $details.ArchiveDate
                PartyFolder = $details.PartyFolder
                Area = $details.Area
                CandidateRecordType = $recordType
                CandidateRecordNo = $recordNo
                MatchConfidence = $confidence
                MatchReason = $reason
                FileName = [string]$child.name
                RelativePath = $relative
                SizeBytes = [Int64]$child.size
                CreatedDateTime = [string]$child.createdDateTime
                LastModifiedDateTime = [string]$child.lastModifiedDateTime
                SharePointUrl = [string]$child.webUrl
            })

            if (($files.Count % 100) -eq 0) {
                Write-Host "[SCAN] $($files.Count) files found across $folderCount folders..."
            }
            if ($MaxFiles -gt 0 -and $files.Count -ge $MaxFiles) {
                $stop = $true
                break
            }
        }
    }
}

if (-not $files.Count) { throw "No files were found under '$RootFolder'." }
Write-Host "[SCAN] Complete. $($files.Count) files across $folderCount folders."

$matched = @($files | Where-Object CandidateRecordNo)
$unmatched = @($files | Where-Object { -not $_.CandidateRecordNo })

$records = foreach ($group in ($matched | Group-Object CandidateRecordType,CandidateRecordNo,PartyFolder,Area)) {
    $items = @($group.Group)
    $first = $items[0]
    [pscustomobject]@{
        RecordType = $first.CandidateRecordType
        RecordNo = $first.CandidateRecordNo
        PartyFolder = $first.PartyFolder
        Area = $first.Area
        DocumentCount = $items.Count
        ExampleFileName = $first.FileName
        Libraries = (($items.LibraryName | Sort-Object -Unique) -join '; ')
        ExampleSharePointUrl = $first.SharePointUrl
        MatchReason = $first.MatchReason
    }
}
$records = @($records | Sort-Object @{Expression='DocumentCount';Descending=$true},RecordType,RecordNo)

$partyFolders = foreach ($group in ($files | Where-Object PartyFolder | Group-Object PartyFolder,Area)) {
    $items = @($group.Group)
    $first = $items[0]
    [pscustomobject]@{
        PartyFolder = $first.PartyFolder
        Area = $first.Area
        DocumentCount = $items.Count
        MatchedRecordDocuments = @($items | Where-Object CandidateRecordNo).Count
        UnmatchedDocuments = @($items | Where-Object { -not $_.CandidateRecordNo }).Count
        Libraries = (($items.LibraryName | Sort-Object -Unique) -join '; ')
        ExampleFileName = $first.FileName
        ExampleSharePointUrl = $first.SharePointUrl
    }
}
$partyFolders = @($partyFolders | Sort-Object @{Expression='DocumentCount';Descending=$true},PartyFolder)

$uat = [System.Collections.Generic.List[object]]::new()
foreach ($typeGroup in ($records | Group-Object RecordType)) {
    $sample = $typeGroup.Group | Sort-Object DocumentCount -Descending | Select-Object -First 1
    if ($sample) { $uat.Add($sample) }
}
foreach ($record in $records) {
    if ($uat.Count -ge $UatSampleCount) { break }
    $exists = @($uat | Where-Object { $_.RecordType -eq $record.RecordType -and $_.RecordNo -eq $record.RecordNo }).Count
    if (-not $exists) { $uat.Add($record) }
}

$allPath = Join-Path $OutputFolder 'Zetadocs-All-Historical-Documents.csv'
$recordsPath = Join-Path $OutputFolder 'Zetadocs-Records-With-Documents.csv'
$partiesPath = Join-Path $OutputFolder 'Zetadocs-Customer-Vendor-Folders.csv'
$unmatchedPath = Join-Path $OutputFolder 'Zetadocs-Unmatched-Documents.csv'
$uatPath = Join-Path $OutputFolder 'Zetadocs-UAT-Sample-Records.csv'
$summaryPath = Join-Path $OutputFolder 'Zetadocs-Inventory-Summary.txt'

$files | Sort-Object RelativePath | Export-Csv $allPath -NoTypeInformation -Encoding UTF8
$records | Export-Csv $recordsPath -NoTypeInformation -Encoding UTF8
$partyFolders | Export-Csv $partiesPath -NoTypeInformation -Encoding UTF8
$unmatched | Sort-Object RelativePath | Export-Csv $unmatchedPath -NoTypeInformation -Encoding UTF8
$uat | Export-Csv $uatPath -NoTypeInformation -Encoding UTF8

@"
Zetadocs Historical Document Inventory
Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

Site:            $SiteUrl
Libraries:       $((@($scanTargets | ForEach-Object { $_.Drive.name }) | Sort-Object -Unique) -join ", ")
Scan start:      library root(s), with folder fallback for $RootFolder
Folders scanned: $folderCount
Files found:     $($files.Count)
Likely BC records found: $($records.Count)
Matched files:   $($matched.Count)
Unmatched files: $($unmatched.Count)
Customer/vendor folders: $($partyFolders.Count)

Open first:
$recordsPath

Customer/vendor fallback list:
$partiesPath

Recommended UAT samples:
$uatPath

This script made no changes to SharePoint.
"@ | Set-Content $summaryPath -Encoding UTF8

Write-Section 'Inventory complete'
Write-Host "Files found:               $($files.Count)"
Write-Host "Likely BC records found:   $($records.Count)"
Write-Host "Customer/vendor folders:   $($partyFolders.Count)"
Write-Host "Unmatched files:           $($unmatched.Count)"
Write-Host ''
Write-Host 'Open this report first:'
Write-Host "  $recordsPath"
Write-Host ''
Write-Host 'Customer/vendor fallback list:'
Write-Host "  $partiesPath"
Write-Host ''
Write-Host 'Recommended UAT samples:'
Write-Host "  $uatPath"
Write-Host ''
Write-Host 'No SharePoint content was changed.'
