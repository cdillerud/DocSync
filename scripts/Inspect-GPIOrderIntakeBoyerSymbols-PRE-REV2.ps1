#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY / GET-ONLY BOYER SYMBOL PACKAGE INSPECTION - REV2
# =====================================================================================================================
$TenantId     = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment  = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName  = 'Gamer Packaging'
$CompanyId    = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv = 'Sandbox_NoZetadocs_UAT'

$OrderIntakeAppId     = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$OrderIntakeAppName   = 'GPI Order Intake'
$OrderIntakePublisher = 'Gamer Packaging Inc'
$OrderIntakeVersion   = '0.1.0.3'

$BoyerAppId     = '65994cd5-4d6f-497e-abc0-767b8c392608'
$BoyerAppName   = 'Boyer And Associates Custom Package'
$BoyerPublisher = 'Boyer And Associates'
$BoyerVersion   = '25.0.0.13'

function Convert-TokenToString {
    param([Parameter(Mandatory)]$TokenValue)
    if ($TokenValue -is [string]) { return $TokenValue }
    if ($TokenValue -is [Security.SecureString]) {
        return [System.Net.NetworkCredential]::new('', $TokenValue).Password
    }
    if ($TokenValue.PSObject.Properties.Name -contains 'SecurePassword') {
        return [System.Net.NetworkCredential]::new('', $TokenValue.SecurePassword).Password
    }
    return [string]$TokenValue
}

function Get-BcToken {
    if (-not (Get-Module -ListAvailable -Name Az.Accounts)) { throw 'Az.Accounts is required.' }
    Import-Module Az.Accounts -ErrorAction Stop
    try {
        $tokenResult = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
        $token = Convert-TokenToString $tokenResult.Token
        if (-not [string]::IsNullOrWhiteSpace($token)) { return $token }
    }
    catch { }

    Write-Host 'Starting Business Central scoped Microsoft sign-in...' -ForegroundColor Yellow
    Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null
    Connect-AzAccount -Tenant $TenantId -AuthScope 'https://api.businesscentral.dynamics.com' -Scope Process -ErrorAction Stop | Out-Null
    $tokenResult = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
    $token = Convert-TokenToString $tokenResult.Token
    if ([string]::IsNullOrWhiteSpace($token)) { throw 'Could not acquire Business Central access token.' }
    return $token
}

function Assert-BcUri {
    param([Parameter(Mandatory)][string]$Uri)
    $parsed = [Uri]$Uri
    if ($parsed.Scheme -ne 'https' -or $parsed.Host -ne 'api.businesscentral.dynamics.com') {
        throw "Unexpected Business Central URI blocked: $Uri"
    }
    if ($Uri.IndexOf($ForbiddenEnv, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Forbidden legacy sandbox URI blocked: $Uri"
    }
    if ($Uri.IndexOf('/Production/', [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Production-like URI blocked: $Uri"
    }
}

function Invoke-BcGet {
    param([Parameter(Mandatory)][string]$Uri, [Parameter(Mandatory)][hashtable]$Headers)
    Assert-BcUri $Uri
    Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 90
}

function Get-InstalledVersionString {
    param([Parameter(Mandatory)]$Extension)
    "$($Extension.versionMajor).$($Extension.versionMinor).$($Extension.versionBuild).$($Extension.versionRevision)"
}

function Assert-InstalledExtension {
    param(
        [Parameter(Mandatory)][object[]]$InstalledExtensions,
        [Parameter(Mandatory)][string]$Id,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Publisher,
        [Parameter(Mandatory)][string]$Version
    )
    $matches = @($InstalledExtensions | Where-Object {
        [string]$_.id -eq $Id -and
        [string]$_.displayName -eq $Name -and
        [string]$_.publisher -eq $Publisher -and
        (Get-InstalledVersionString -Extension $_) -eq $Version
    })
    if ($matches.Count -ne 1) { throw "Expected exactly one installed $Name $Version; found $($matches.Count)." }
    $matches[0]
}

function Get-ArchiveEntryName {
    param([Parameter(Mandatory)]$Entry)
    $type = $Entry.GetType()
    $prop = $type.GetProperty('FullName')
    if ($null -eq $prop) { $prop = $type.GetProperty('Name') }
    if ($null -eq $prop) {
        throw "Archive entry type '$($type.FullName)' exposes neither FullName nor Name."
    }
    [string]$prop.GetValue($Entry)
}

function Get-ArchiveEntryLength {
    param([Parameter(Mandatory)]$Entry)
    $prop = $Entry.GetType().GetProperty('Length')
    if ($null -eq $prop) { return [int64]0 }
    [int64]$prop.GetValue($Entry)
}

function Read-ZipEntryText {
    param([Parameter(Mandatory)]$Entry)
    $stream = $Entry.Open()
    try {
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $true)
        try { $reader.ReadToEnd() }
        finally { $reader.Dispose() }
    }
    finally { $stream.Dispose() }
}

function Get-TermHits {
    param(
        [Parameter(Mandatory)][string]$EntryName,
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string[]]$Terms,
        [int]$MaxHits = 150
    )
    $hits = [System.Collections.Generic.List[object]]::new()
    $lines = $Text -split "`r?`n"
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = [string]$lines[$i]
        foreach ($term in $Terms) {
            if ($line.IndexOf($term, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
                $display = $line.Trim()
                if ($display.Length -gt 280) { $display = $display.Substring(0, 280) + '...' }
                $hits.Add([pscustomobject][ordered]@{ entry = $EntryName; line = $i + 1; term = $term; text = $display })
                break
            }
        }
        if ($hits.Count -ge $MaxHits) { break }
    }
    @($hits)
}

# Fail closed.
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

$environmentResponse = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $headers
$environmentMatches = @($environmentResponse.value | Where-Object { [string]$_.name -eq $Environment })
if ($environmentMatches.Count -ne 1) { throw "Expected exactly one $Environment environment; found $($environmentMatches.Count)." }
$environmentType = [string]$environmentMatches[0].type
if ($environmentType -ine 'sandbox') { throw "SAFETY STOP: $Environment is type '$environmentType', not sandbox." }

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet -Uri "$standardRoot/companies" -Headers $headers
$companyMatches = @($companies.value | Where-Object {
    [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatches.Count -ne 1) { throw "Exact Gamer Packaging company verification failed; found $($companyMatches.Count)." }

$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$installedExtensions = @($extensions.value | Where-Object { $_.isInstalled -eq $true })
$null = Assert-InstalledExtension -InstalledExtensions $installedExtensions -Id $OrderIntakeAppId -Name $OrderIntakeAppName -Publisher $OrderIntakePublisher -Version $OrderIntakeVersion
$null = Assert-InstalledExtension -InstalledExtensions $installedExtensions -Id $BoyerAppId -Name $BoyerAppName -Publisher $BoyerPublisher -Version $BoyerVersion

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - BOYER SYMBOL PACKAGE INSPECTION REV2 / PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Installed GPI app : $OrderIntakeAppName $OrderIntakeVersion"
Write-Host "Target extension  : $BoyerAppName $BoyerVersion"
Write-Host "Target app ID     : $BoyerAppId"
Write-Host 'Archive reader    : REFLECTION-HARDENED ZIP ENTRY INSPECTION'
Write-Host 'BC operations     : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation: NONE' -ForegroundColor Green
Write-Host 'Business data     : NOT READ / NOT WRITTEN' -ForegroundColor Green
Write-Host 'Sales-order action: NOT CALLED' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("GPIOrderIntake-BoyerSymbols-" + [Guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($tempRoot) | Out-Null
$packagePath = Join-Path $tempRoot 'Boyer_Custom_Package_25.0.0.13.app'
$downloadAttempts = [System.Collections.Generic.List[object]]::new()
$downloaded = $false

$symbolUris = @(
    "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/dev/packages?appId=$BoyerAppId&versionText=$BoyerVersion",
    "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/dev/packages?publisher=$([Uri]::EscapeDataString($BoyerPublisher))&appName=$([Uri]::EscapeDataString($BoyerAppName))&versionText=$BoyerVersion"
)

foreach ($symbolUri in $symbolUris) {
    Assert-BcUri $symbolUri
    try {
        Invoke-WebRequest -Method Get -Uri $symbolUri -Headers @{ Authorization = "Bearer $token" } -OutFile $packagePath -TimeoutSec 120
        if ((Test-Path $packagePath) -and (Get-Item $packagePath).Length -gt 0) {
            $downloadAttempts.Add([pscustomobject]@{ uriShape = if ($symbolUri -match 'appId=') { 'APP_ID' } else { 'PUBLISHER_NAME' }; success = $true; error = $null })
            $downloaded = $true
            break
        }
        throw 'Response did not produce a non-empty package file.'
    }
    catch {
        $downloadAttempts.Add([pscustomobject]@{ uriShape = if ($symbolUri -match 'appId=') { 'APP_ID' } else { 'PUBLISHER_NAME' }; success = $false; error = $_.Exception.Message })
        Remove-Item $packagePath -Force -ErrorAction SilentlyContinue
    }
}

if (-not $downloaded) {
    [ordered]@{
        success = $false
        mode = 'GET_ONLY_BOYER_SYMBOL_PACKAGE_INSPECTION_REV2'
        packageDownloaded = $false
        downloadAttempts = @($downloadAttempts)
        safety = [ordered]@{ bcOperations='GET ONLY'; extensionMutation='NONE'; businessData='NOT READ / NOT WRITTEN'; salesOrderAction='NOT CALLED'; production='HARD BLOCKED' }
    } | ConvertTo-Json -Depth 10
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    return
}

$packageInfo = Get-Item $packagePath
$packageHash = (Get-FileHash -Path $packagePath -Algorithm SHA256).Hash
$headerBytes = [System.IO.File]::ReadAllBytes($packagePath) | Select-Object -First 32
$headerHex = ($headerBytes | ForEach-Object { $_.ToString('X2') }) -join ' '

Add-Type -AssemblyName System.IO.Compression
$fileStream = $null
$zip = $null
try {
    $fileStream = [System.IO.File]::Open($packagePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
    $zip = [System.IO.Compression.ZipArchive]::new($fileStream, [System.IO.Compression.ZipArchiveMode]::Read, $false)

    $entryRecords = [System.Collections.Generic.List[object]]::new()
    for ($i = 0; $i -lt $zip.Entries.Count; $i++) {
        $entry = $zip.Entries[$i]
        if ($null -eq $entry) { throw "Archive entry index $i is null." }
        $typeName = $entry.GetType().FullName
        $name = Get-ArchiveEntryName -Entry $entry
        $length = Get-ArchiveEntryLength -Entry $entry
        $entryRecords.Add([pscustomobject]@{ index=$i; name=$name; length=$length; type=$typeName; entry=$entry })
    }

    $sourceEntries = @($entryRecords | Where-Object { $_.name -match '(?i)\.al$' })
    $symbolEntries = @($entryRecords | Where-Object { $_.name -match '(?i)SymbolReference\.json$' })
    $manifestEntries = @($entryRecords | Where-Object { $_.name -match '(?i)(NavxManifest\.xml|app\.json)$' })

    $terms = @(
        'OnCopyFromItemOnAfterCheck','codeunit 50500','codeunit 50001','Unit Price','UpdateUnitPrice',
        'Price Calculation','Sales Price','Price List','Customer Price','Line Discount','GIOVANN',
        'C-503003-12033922','277.99','Location Code','Unit of Measure'
    )

    $sourceHits = [System.Collections.Generic.List[object]]::new()
    foreach ($rec in $sourceEntries) {
        if ($rec.length -gt 10MB) { continue }
        $text = Read-ZipEntryText -Entry $rec.entry
        foreach ($hit in @(Get-TermHits -EntryName $rec.name -Text $text -Terms $terms -MaxHits 80)) {
            if ($sourceHits.Count -ge 240) { break }
            $sourceHits.Add($hit)
        }
        if ($sourceHits.Count -ge 240) { break }
    }

    $symbolHits = [System.Collections.Generic.List[object]]::new()
    foreach ($rec in $symbolEntries) {
        if ($rec.length -gt 50MB) { continue }
        $text = Read-ZipEntryText -Entry $rec.entry
        foreach ($hit in @(Get-TermHits -EntryName $rec.name -Text $text -Terms @('50500','50001','OnCopyFromItemOnAfterCheck','Unit Price','UpdateUnitPrice','Price') -MaxHits 120)) {
            if ($symbolHits.Count -ge 200) { break }
            $symbolHits.Add($hit)
        }
        if ($symbolHits.Count -ge 200) { break }
    }

    $resourceExposureHits = [System.Collections.Generic.List[object]]::new()
    foreach ($rec in $manifestEntries) {
        if ($rec.length -gt 5MB) { continue }
        $text = Read-ZipEntryText -Entry $rec.entry
        foreach ($hit in @(Get-TermHits -EntryName $rec.name -Text $text -Terms @('resourceExposurePolicy','allowDebugging','allowDownloadingSource','includeSourceInSymbolFile','showMyCode') -MaxHits 40)) {
            $resourceExposureHits.Add($hit)
        }
    }

    $sourceOutcome = if ($sourceEntries.Count -gt 0) { 'SOURCE_PRESENT_IN_SYMBOL_PACKAGE' } elseif ($symbolEntries.Count -gt 0) { 'SYMBOL_METADATA_ONLY_NO_AL_SOURCE' } else { 'NO_SOURCE_OR_SYMBOL_REFERENCE_FOUND' }

    $result = [ordered]@{
        success = $true
        mode = 'GET_ONLY_BOYER_SYMBOL_PACKAGE_INSPECTION_REV2'
        environment = $Environment
        environmentType = $environmentType
        company = $CompanyName
        targetExtension = [ordered]@{ id=$BoyerAppId; name=$BoyerAppName; publisher=$BoyerPublisher; version=$BoyerVersion }
        packageDownloaded = $true
        downloadAttempts = @($downloadAttempts)
        package = [ordered]@{
            sizeBytes = $packageInfo.Length
            sha256 = $packageHash
            first32BytesHex = $headerHex
            archiveType = $zip.GetType().FullName
            archiveEntryCount = $entryRecords.Count
            firstEntryRuntimeType = if ($entryRecords.Count -gt 0) { $entryRecords[0].type } else { $null }
            firstEntryName = if ($entryRecords.Count -gt 0) { $entryRecords[0].name } else { $null }
            sourceFileCount = $sourceEntries.Count
            symbolReferenceCount = $symbolEntries.Count
            manifestEntryCount = $manifestEntries.Count
            sourceInspectionOutcome = $sourceOutcome
        }
        sourceFiles = @($sourceEntries | Select-Object -First 100 | ForEach-Object { $_.name })
        resourceExposureHits = @($resourceExposureHits)
        sourceSearchHits = @($sourceHits)
        symbolMetadataHits = @($symbolHits)
        interpretation = [ordered]@{
            sourceAvailable = ($sourceEntries.Count -gt 0)
            onCopyFromItemSourceHit = (@($sourceHits | Where-Object { $_.term -eq 'OnCopyFromItemOnAfterCheck' }).Count -gt 0)
            unitPriceSourceHit = (@($sourceHits | Where-Object { $_.term -in @('Unit Price','UpdateUnitPrice') }).Count -gt 0)
            giovanniLiteralSourceHit = (@($sourceHits | Where-Object { $_.term -eq 'GIOVANN' }).Count -gt 0)
            itemLiteralSourceHit = (@($sourceHits | Where-Object { $_.term -eq 'C-503003-12033922' }).Count -gt 0)
            observedPriceLiteralSourceHit = (@($sourceHits | Where-Object { $_.term -eq '277.99' }).Count -gt 0)
            note = 'Symbol metadata identifies objects/procedures but does not prove implementation behavior. AL source hits are stronger evidence when source exposure is enabled.'
        }
        safety = [ordered]@{
            bcOperations='GET ONLY'; extensionMutation='NONE'; businessData='NOT READ / NOT WRITTEN'; salesOrderAction='NOT CALLED'; localTempPackage='DELETED AFTER INSPECTION'; production='HARD BLOCKED'
        }
    }

    $result | ConvertTo-Json -Depth 12
    Write-Host ''
    Write-Host 'GPI ORDER INTAKE BOYER SYMBOL PACKAGE INSPECTION REV2: GET-ONLY PASS' -ForegroundColor Green
}
catch {
    $entryTypeEvidence = $null
    try {
        if ($null -ne $zip -and $zip.Entries.Count -gt 0 -and $null -ne $zip.Entries[0]) {
            $first = $zip.Entries[0]
            $entryTypeEvidence = [ordered]@{
                runtimeType = $first.GetType().FullName
                reflectedProperties = @($first.GetType().GetProperties() | ForEach-Object { $_.Name } | Sort-Object)
            }
        }
    }
    catch { }

    [ordered]@{
        success = $false
        mode = 'GET_ONLY_BOYER_SYMBOL_PACKAGE_INSPECTION_REV2'
        error = $_.Exception.Message
        package = [ordered]@{ sizeBytes=$packageInfo.Length; sha256=$packageHash; first32BytesHex=$headerHex; firstEntryEvidence=$entryTypeEvidence }
        conclusion = 'Local archive inspection failed after a successful GET-only package download. Evidence is emitted without BC mutation.'
        safety = [ordered]@{ bcOperations='GET ONLY'; extensionMutation='NONE'; businessData='NOT READ / NOT WRITTEN'; salesOrderAction='NOT CALLED'; localTempPackage='DELETED AFTER INSPECTION'; production='HARD BLOCKED' }
    } | ConvertTo-Json -Depth 12
    Write-Host ''
    Write-Host 'GPI ORDER INTAKE BOYER SYMBOL PACKAGE INSPECTION REV2: SAFE LOCAL INSPECTION STOP' -ForegroundColor Yellow
}
finally {
    if ($null -ne $zip) { $zip.Dispose() }
    if ($null -ne $fileStream) { $fileStream.Dispose() }
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
