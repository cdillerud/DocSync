#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY / GET-ONLY BOYER SYMBOL PACKAGE INSPECTION REV3
# NAVX-aware: validates NAVX envelope, locates embedded ZIP payload, inspects locally.
# =====================================================================================================================
$TenantId     = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment  = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName  = 'Gamer Packaging'
$CompanyId    = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv = 'Sandbox_NoZetadocs_UAT'

$OrderIntakeAppId        = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$OrderIntakeAppName      = 'GPI Order Intake'
$OrderIntakePublisher    = 'Gamer Packaging Inc'
$OrderIntakeVersion      = '0.1.0.3'

$BoyerAppId       = '65994cd5-4d6f-497e-abc0-767b8c392608'
$BoyerAppName     = 'Boyer And Associates Custom Package'
$BoyerPublisher   = 'Boyer And Associates'
$BoyerVersion     = '25.0.0.13'

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
    if (-not (Get-Module -ListAvailable -Name Az.Accounts)) {
        throw 'Az.Accounts is required.'
    }
    Import-Module Az.Accounts -ErrorAction Stop

    try {
        $tokenResult = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
        $token = Convert-TokenToString $tokenResult.Token
        if (-not [string]::IsNullOrWhiteSpace($token)) { return $token }
    }
    catch {
        # Fall through to isolated interactive BC-scoped authentication.
    }

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
    return "$($Extension.versionMajor).$($Extension.versionMinor).$($Extension.versionBuild).$($Extension.versionRevision)"
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
    if ($matches.Length -ne 1) {
        throw "Expected exactly one installed $Name $Version; found $($matches.Length)."
    }
    return $matches[0]
}

function Get-HexPrefix {
    param([Parameter(Mandatory)][byte[]]$Bytes, [int]$Length = 32)
    $take = [Math]::Min($Length, $Bytes.Length)
    if ($take -le 0) { return '' }
    return (($Bytes[0..($take - 1)] | ForEach-Object { $_.ToString('X2') }) -join ' ')
}

function Find-ZipLocalHeaderOffset {
    param([Parameter(Mandatory)][byte[]]$Bytes, [int]$SearchLimit = 256)
    $limit = [Math]::Min($SearchLimit, $Bytes.Length - 4)
    if ($limit -lt 0) { return -1 }
    for ($i = 0; $i -le $limit; $i++) {
        if ($Bytes[$i] -eq 0x50 -and $Bytes[$i + 1] -eq 0x4B -and $Bytes[$i + 2] -eq 0x03 -and $Bytes[$i + 3] -eq 0x04) {
            return $i
        }
    }
    return -1
}

function Get-EntryName {
    param([Parameter(Mandatory)]$Entry)
    $type = $Entry.GetType()
    $prop = $type.GetProperty('FullName')
    if ($null -eq $prop) { throw "ZIP entry type '$($type.FullName)' does not expose FullName." }
    return [string]$prop.GetValue($Entry)
}

function Get-EntryLength {
    param([Parameter(Mandatory)]$Entry)
    $type = $Entry.GetType()
    $prop = $type.GetProperty('Length')
    if ($null -eq $prop) { return [int64]0 }
    return [int64]$prop.GetValue($Entry)
}

function Read-ZipEntryText {
    param([Parameter(Mandatory)]$Entry)
    $stream = $Entry.Open()
    try {
        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8, $true)
        try { return $reader.ReadToEnd() }
        finally { $reader.Dispose() }
    }
    finally { $stream.Dispose() }
}

function Add-TermHits {
    param(
        [Parameter(Mandatory)]$Entry,
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string[]]$Terms,
        [Parameter(Mandatory)][System.Collections.Generic.List[object]]$Destination,
        [int]$MaxTotal = 200
    )

    $entryName = Get-EntryName -Entry $Entry
    $lines = $Text -split "`r?`n"
    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = [string]$lines[$i]
        foreach ($term in $Terms) {
            if ($line.IndexOf($term, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
                $display = $line.Trim()
                if ($display.Length -gt 260) { $display = $display.Substring(0, 260) + '...' }
                $Destination.Add([pscustomobject][ordered]@{
                    entry = $entryName
                    line = $i + 1
                    term = $term
                    text = $display
                })
                break
            }
        }
        if ($Destination.Count -ge $MaxTotal) { break }
    }
}

# ---------------------------------------------------------------------------------------------------------------------
# Fail closed. GET only against BC; local temp-file operations only.
# ---------------------------------------------------------------------------------------------------------------------
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

$environmentResponse = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $headers
$environmentMatches = @($environmentResponse.value | Where-Object { [string]$_.name -eq $Environment })
if ($environmentMatches.Length -ne 1) {
    throw "Expected exactly one $Environment environment; found $($environmentMatches.Length)."
}
$environmentType = [string]$environmentMatches[0].type
if ($environmentType -ine 'sandbox') {
    throw "SAFETY STOP: $Environment is type '$environmentType', not sandbox."
}

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet -Uri "$standardRoot/companies" -Headers $headers
$companyMatches = @($companies.value | Where-Object {
    [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatches.Length -ne 1) {
    throw "Exact Gamer Packaging company verification failed; found $($companyMatches.Length)."
}

$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$installedExtensions = @($extensions.value | Where-Object { $_.isInstalled -eq $true })
$null = Assert-InstalledExtension -InstalledExtensions $installedExtensions -Id $OrderIntakeAppId -Name $OrderIntakeAppName -Publisher $OrderIntakePublisher -Version $OrderIntakeVersion
$null = Assert-InstalledExtension -InstalledExtensions $installedExtensions -Id $BoyerAppId -Name $BoyerAppName -Publisher $BoyerPublisher -Version $BoyerVersion

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - BOYER SYMBOL PACKAGE INSPECTION REV3 / NAVX-AWARE / PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Installed GPI app : $OrderIntakeAppName $OrderIntakeVersion"
Write-Host "Target extension  : $BoyerAppName $BoyerVersion"
Write-Host "Target app ID     : $BoyerAppId"
Write-Host 'Archive reader    : NAVX ENVELOPE -> EMBEDDED ZIP PAYLOAD'
Write-Host 'BC operations     : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation: NONE' -ForegroundColor Green
Write-Host 'Business data     : NOT READ / NOT WRITTEN' -ForegroundColor Green
Write-Host 'Sales-order action: NOT CALLED' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("GPIOrderIntake-BoyerSymbolsREV3-" + [Guid]::NewGuid().ToString('N'))
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
        mode = 'GET_ONLY_BOYER_SYMBOL_PACKAGE_INSPECTION_REV3'
        targetExtension = "$BoyerAppName $BoyerVersion"
        packageDownloaded = $false
        downloadAttempts = @($downloadAttempts)
        safety = [ordered]@{
            bcOperations = 'GET ONLY'; extensionMutation = 'NONE'; businessData = 'NOT READ / NOT WRITTEN'; salesOrderAction = 'NOT CALLED'; production = 'HARD BLOCKED'
        }
    } | ConvertTo-Json -Depth 10
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    return
}

$packageInfo = Get-Item $packagePath
$packageHash = (Get-FileHash -Path $packagePath -Algorithm SHA256).Hash
$bytes = [System.IO.File]::ReadAllBytes($packagePath)
$first32 = Get-HexPrefix -Bytes $bytes -Length 32
$navxSignature = if ($bytes.Length -ge 4) { [System.Text.Encoding]::ASCII.GetString($bytes, 0, 4) } else { '' }
$declaredHeaderLength = if ($bytes.Length -ge 8) { [BitConverter]::ToUInt32($bytes, 4) } else { 0 }
$zipOffset = Find-ZipLocalHeaderOffset -Bytes $bytes -SearchLimit 256

if ($navxSignature -ne 'NAVX') {
    throw "Downloaded package does not begin with NAVX. First bytes: $first32"
}
if ($zipOffset -lt 0) {
    [ordered]@{
        success = $false
        mode = 'GET_ONLY_BOYER_SYMBOL_PACKAGE_INSPECTION_REV3'
        package = [ordered]@{
            sizeBytes = $packageInfo.Length
            sha256 = $packageHash
            first32BytesHex = $first32
            navxSignature = $navxSignature
            declaredHeaderLength = $declaredHeaderLength
            embeddedZipOffset = $zipOffset
        }
        conclusion = 'NAVX package downloaded, but no embedded ZIP local-header signature was found in the first 256 bytes. The package may be runtime/encrypted or use an unsupported envelope.'
        safety = [ordered]@{
            bcOperations = 'GET ONLY'; extensionMutation = 'NONE'; businessData = 'NOT READ / NOT WRITTEN'; salesOrderAction = 'NOT CALLED'; localTempPackage = 'DELETED AFTER INSPECTION'; production = 'HARD BLOCKED'
        }
    } | ConvertTo-Json -Depth 10
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    return
}

Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop
$payloadLength = $bytes.Length - $zipOffset
$payloadBytes = [byte[]]::new($payloadLength)
[Array]::Copy($bytes, $zipOffset, $payloadBytes, 0, $payloadLength)
$memory = [System.IO.MemoryStream]::new($payloadBytes, $false)
$zip = $null

try {
    $zip = [System.IO.Compression.ZipArchive]::new($memory, [System.IO.Compression.ZipArchiveMode]::Read, $false)

    $entryNames = [System.Collections.Generic.List[string]]::new()
    $sourceEntries = [System.Collections.Generic.List[object]]::new()
    $symbolEntries = [System.Collections.Generic.List[object]]::new()
    $manifestEntries = [System.Collections.Generic.List[object]]::new()
    $entryCount = 0
    $firstEntryRuntimeType = $null
    $firstEntryName = $null

    foreach ($entry in $zip.Entries) {
        $entryCount++
        $name = Get-EntryName -Entry $entry
        if ($entryCount -eq 1) {
            $firstEntryRuntimeType = $entry.GetType().FullName
            $firstEntryName = $name
        }
        $entryNames.Add($name)
        if ($name -match '(?i)\.al$') { $sourceEntries.Add($entry) }
        if ($name -match '(?i)SymbolReference\.json$') { $symbolEntries.Add($entry) }
        if ($name -match '(?i)(NavxManifest\.xml|app\.json)$') { $manifestEntries.Add($entry) }
    }

    $terms = @(
        'OnCopyFromItemOnAfterCheck', 'codeunit 50500', 'codeunit 50001', 'Unit Price', 'UpdateUnitPrice',
        'Price Calculation', 'Sales Price', 'Price List', 'Customer Price', 'Line Discount', 'GIOVANN',
        'C-503003-12033922', '277.99', 'Location Code', 'Unit of Measure'
    )

    $sourceHits = [System.Collections.Generic.List[object]]::new()
    foreach ($entry in $sourceEntries) {
        if ((Get-EntryLength -Entry $entry) -gt 10MB) { continue }
        $text = Read-ZipEntryText -Entry $entry
        Add-TermHits -Entry $entry -Text $text -Terms $terms -Destination $sourceHits -MaxTotal 240
        if ($sourceHits.Count -ge 240) { break }
    }

    $symbolHits = [System.Collections.Generic.List[object]]::new()
    foreach ($entry in $symbolEntries) {
        if ((Get-EntryLength -Entry $entry) -gt 75MB) { continue }
        $text = Read-ZipEntryText -Entry $entry
        Add-TermHits -Entry $entry -Text $text -Terms @('50500','50001','OnCopyFromItemOnAfterCheck','Unit Price','UpdateUnitPrice','Price') -Destination $symbolHits -MaxTotal 180
        if ($symbolHits.Count -ge 180) { break }
    }

    $resourceExposureHits = [System.Collections.Generic.List[object]]::new()
    foreach ($entry in $manifestEntries) {
        if ((Get-EntryLength -Entry $entry) -gt 5MB) { continue }
        $text = Read-ZipEntryText -Entry $entry
        Add-TermHits -Entry $entry -Text $text -Terms @('ResourceExposurePolicy','AllowDebugging','AllowDownloadingSource','IncludeSourceInSymbolFile','ShowMyCode') -Destination $resourceExposureHits -MaxTotal 50
    }

    $sourceOutcome = if ($sourceEntries.Count -gt 0) {
        'SOURCE_PRESENT_IN_SYMBOL_PACKAGE'
    }
    elseif ($symbolEntries.Count -gt 0) {
        'SYMBOL_METADATA_ONLY_NO_AL_SOURCE'
    }
    else {
        'NO_SOURCE_OR_SYMBOL_REFERENCE_FOUND'
    }

    $sourceFiles = @()
    foreach ($entry in $sourceEntries) {
        if ($sourceFiles.Length -ge 100) { break }
        $sourceFiles += (Get-EntryName -Entry $entry)
    }

    $result = [ordered]@{
        success = $true
        mode = 'GET_ONLY_BOYER_SYMBOL_PACKAGE_INSPECTION_REV3'
        environment = $Environment
        environmentType = $environmentType
        company = $CompanyName
        targetExtension = [ordered]@{ id = $BoyerAppId; name = $BoyerAppName; publisher = $BoyerPublisher; version = $BoyerVersion }
        package = [ordered]@{
            sizeBytes = $packageInfo.Length
            sha256 = $packageHash
            first32BytesHex = $first32
            navxSignature = $navxSignature
            declaredHeaderLength = $declaredHeaderLength
            embeddedZipOffset = $zipOffset
            declaredHeaderMatchesZipOffset = ([uint32]$zipOffset -eq $declaredHeaderLength)
            zipPayloadBytes = $payloadLength
            archiveEntryCount = $entryCount
            firstEntryRuntimeType = $firstEntryRuntimeType
            firstEntryName = $firstEntryName
            sourceFileCount = $sourceEntries.Count
            symbolReferenceCount = $symbolEntries.Count
            manifestEntryCount = $manifestEntries.Count
            sourceInspectionOutcome = $sourceOutcome
        }
        sourceFiles = $sourceFiles
        resourceExposureHits = @($resourceExposureHits)
        sourceSearchHits = @($sourceHits)
        symbolMetadataHits = @($symbolHits)
        interpretation = [ordered]@{
            sourceAvailable = ($sourceEntries.Count -gt 0)
            onCopyFromItemSourceHit = (@($sourceHits | Where-Object { $_.term -eq 'OnCopyFromItemOnAfterCheck' }).Length -gt 0)
            unitPriceSourceHit = (@($sourceHits | Where-Object { $_.term -in @('Unit Price','UpdateUnitPrice') }).Length -gt 0)
            giovanniLiteralSourceHit = (@($sourceHits | Where-Object { $_.term -eq 'GIOVANN' }).Length -gt 0)
            itemLiteralSourceHit = (@($sourceHits | Where-Object { $_.term -eq 'C-503003-12033922' }).Length -gt 0)
            observedPriceLiteralSourceHit = (@($sourceHits | Where-Object { $_.term -eq '277.99' }).Length -gt 0)
            note = 'AL source hits are implementation evidence when source is exposed. SymbolReference metadata alone describes object/procedure surface and is not proof of pricing behavior.'
        }
        safety = [ordered]@{
            bcOperations = 'GET ONLY'
            extensionMutation = 'NONE'
            businessData = 'NOT READ / NOT WRITTEN'
            salesOrderAction = 'NOT CALLED'
            localTempPackage = 'DELETED AFTER INSPECTION'
            production = 'HARD BLOCKED'
        }
    }

    $result | ConvertTo-Json -Depth 14
    Write-Host ''
    Write-Host 'GPI ORDER INTAKE BOYER SYMBOL PACKAGE INSPECTION REV3: GET-ONLY PASS' -ForegroundColor Green
}
finally {
    if ($null -ne $zip) { $zip.Dispose() }
    $memory.Dispose()
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
