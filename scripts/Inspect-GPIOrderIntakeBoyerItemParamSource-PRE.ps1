#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY / GET-ONLY BOYER ITEM PARAMETER SOURCE TRACE
# Purpose: identify the custom ItemParam table used by Customer Item Sales List and trace how its last-sale fields are set.
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
    catch {}

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
    if ($matches.Length -ne 1) { throw "Expected exactly one installed $Name $Version; found $($matches.Length)." }
}

function Find-ZipLocalHeaderOffset {
    param([Parameter(Mandatory)][byte[]]$Bytes, [int]$SearchLimit = 256)
    $limit = [Math]::Min($SearchLimit, $Bytes.Length - 4)
    for ($i = 0; $i -le $limit; $i++) {
        if ($Bytes[$i] -eq 0x50 -and $Bytes[$i + 1] -eq 0x4B -and $Bytes[$i + 2] -eq 0x03 -and $Bytes[$i + 3] -eq 0x04) {
            return $i
        }
    }
    return -1
}

function Get-EntryName {
    param([Parameter(Mandatory)]$Entry)
    $prop = $Entry.GetType().GetProperty('FullName')
    if ($null -eq $prop) { throw "ZIP entry type '$($Entry.GetType().FullName)' does not expose FullName." }
    return [string]$prop.GetValue($Entry)
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

function New-SourceContext {
    param(
        [Parameter(Mandatory)][string]$EntryName,
        [Parameter(Mandatory)][AllowEmptyString()][string[]]$Lines,
        [Parameter(Mandatory)][int]$MatchIndex,
        [Parameter(Mandatory)][string]$Rule,
        [int]$Before = 12,
        [int]$After = 20
    )
    $start = [Math]::Max(0, $MatchIndex - $Before)
    $end = [Math]::Min($Lines.Length - 1, $MatchIndex + $After)
    $excerpt = [System.Collections.Generic.List[string]]::new()
    for ($i = $start; $i -le $end; $i++) {
        $marker = if ($i -eq $MatchIndex) { '>>' } else { '  ' }
        $excerpt.Add(('{0} {1,5}: {2}' -f $marker, ($i + 1), [string]$Lines[$i]))
    }
    return [pscustomobject][ordered]@{
        entry = $EntryName
        matchLine = $MatchIndex + 1
        rule = $Rule
        excerptStartLine = $start + 1
        excerptEndLine = $end + 1
        excerpt = @($excerpt)
    }
}

# ---------------------------------------------------------------------------------------------------------------------
# Hard gates
# ---------------------------------------------------------------------------------------------------------------------
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

$environmentResponse = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $headers
$environmentMatches = @($environmentResponse.value | Where-Object { [string]$_.name -eq $Environment })
if ($environmentMatches.Length -ne 1) { throw "Expected exactly one $Environment environment; found $($environmentMatches.Length)." }
$environmentType = [string]$environmentMatches[0].type
if ($environmentType -ine 'sandbox') { throw "SAFETY STOP: $Environment is type '$environmentType', not sandbox." }

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet -Uri "$standardRoot/companies" -Headers $headers
$companyMatches = @($companies.value | Where-Object {
    [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatches.Length -ne 1) { throw "Exact Gamer Packaging company verification failed; found $($companyMatches.Length)." }

$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$installedExtensions = @($extensions.value | Where-Object { $_.isInstalled -eq $true })
Assert-InstalledExtension -InstalledExtensions $installedExtensions -Id $OrderIntakeAppId -Name $OrderIntakeAppName -Publisher $OrderIntakePublisher -Version $OrderIntakeVersion
Assert-InstalledExtension -InstalledExtensions $installedExtensions -Id $BoyerAppId -Name $BoyerAppName -Publisher $BoyerPublisher -Version $BoyerVersion

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - BOYER ITEM PARAMETER SOURCE TRACE / PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Installed GPI app : $OrderIntakeAppName $OrderIntakeVersion"
Write-Host "Target extension  : $BoyerAppName $BoyerVersion"
Write-Host 'Focus             : ItemParam table / Last Unit Price / Last Sold Qty / Last Sold UOM provenance'
Write-Host 'BC operations     : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation: NONE' -ForegroundColor Green
Write-Host 'Business data     : NOT READ / NOT WRITTEN' -ForegroundColor Green
Write-Host 'Sales-order action: NOT CALLED' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("GPIOrderIntake-BoyerItemParam-" + [Guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($tempRoot) | Out-Null
$packagePath = Join-Path $tempRoot 'Boyer_Custom_Package_25.0.0.13.app'

try {
    $symbolUri = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/dev/packages?appId=$BoyerAppId&versionText=$BoyerVersion"
    Assert-BcUri $symbolUri
    Invoke-WebRequest -Method Get -Uri $symbolUri -Headers @{ Authorization = "Bearer $token" } -OutFile $packagePath -TimeoutSec 120
    if (-not (Test-Path $packagePath) -or (Get-Item $packagePath).Length -le 0) { throw 'Boyer source package download did not produce a non-empty file.' }

    $bytes = [System.IO.File]::ReadAllBytes($packagePath)
    if ($bytes.Length -lt 4 -or [System.Text.Encoding]::ASCII.GetString($bytes, 0, 4) -ne 'NAVX') { throw 'Downloaded Boyer package is not NAVX.' }
    $zipOffset = Find-ZipLocalHeaderOffset -Bytes $bytes
    if ($zipOffset -lt 0) { throw 'NAVX package did not contain a ZIP local header in the first 256 bytes.' }

    $payloadLength = $bytes.Length - $zipOffset
    $payloadBytes = [byte[]]::new($payloadLength)
    [Array]::Copy($bytes, $zipOffset, $payloadBytes, 0, $payloadLength)

    Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop
    $memory = [System.IO.MemoryStream]::new($payloadBytes, $false)
    $zip = [System.IO.Compression.ZipArchive]::new($memory, [System.IO.Compression.ZipArchiveMode]::Read, $false)
    try {
        $source = [System.Collections.Generic.Dictionary[string,string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($entry in $zip.Entries) {
            $entryName = Get-EntryName -Entry $entry
            if ($entryName -notmatch '(?i)\.al$') { continue }
            $source[$entryName] = Read-ZipEntryText -Entry $entry
        }

        $pagePath = 'src/src/page/Pag50002.CustomerItemSalesList.al'
        if (-not $source.ContainsKey($pagePath)) { throw "Expected Boyer page source not found: $pagePath" }
        $pageText = $source[$pagePath]
        $pageLines = [string[]]($pageText -split "`r?`n")

        $itemParamDeclarations = [System.Collections.Generic.List[object]]::new()
        $itemParamRecordNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        for ($i = 0; $i -lt $pageLines.Length; $i++) {
            $line = [string]$pageLines[$i]
            if ($line -match '(?i)\bItemParam\s*:\s*Record\s+(?:"([^"]+)"|([A-Za-z0-9_ .-]+))\s*;') {
                $recordName = if (-not [string]::IsNullOrWhiteSpace($Matches[1])) { $Matches[1].Trim() } else { $Matches[2].Trim() }
                $null = $itemParamRecordNames.Add($recordName)
                $itemParamDeclarations.Add((New-SourceContext -EntryName $pagePath -Lines $pageLines -MatchIndex $i -Rule 'ItemParamRecordDeclaration' -Before 8 -After 12))
            }
        }

        $tableDefinitions = [System.Collections.Generic.List[object]]::new()
        $fieldDefinitionContexts = [System.Collections.Generic.List[object]]::new()
        $populationContexts = [System.Collections.Generic.List[object]]::new()
        $consumerContexts = [System.Collections.Generic.List[object]]::new()
        $tableIds = [System.Collections.Generic.HashSet[int]]::new()
        $fieldTerms = @('Last Unit Price','Last Sold Quantity','Last Sold Unit of Measure Code','Sell-To Customer No.','Item No.','Last Unit Cost')

        foreach ($kvp in $source.GetEnumerator()) {
            $entryName = [string]$kvp.Key
            $text = [string]$kvp.Value
            $lines = [string[]]($text -split "`r?`n")

            for ($i = 0; $i -lt $lines.Length; $i++) {
                $line = [string]$lines[$i]

                foreach ($recordName in $itemParamRecordNames) {
                    $escaped = [regex]::Escape($recordName)
                    if ($line -match "(?i)^\s*table\s+(\d+)\s+\"?$escaped\"?\s*$") {
                        $null = $tableIds.Add([int]$Matches[1])
                        $tableDefinitions.Add((New-SourceContext -EntryName $entryName -Lines $lines -MatchIndex $i -Rule "ItemParamTableDefinition:$recordName" -Before 2 -After 80))
                    }
                }

                foreach ($term in $fieldTerms) {
                    if ($line.IndexOf($term, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
                        if ($entryName -match '(?i)/table/') {
                            $fieldDefinitionContexts.Add((New-SourceContext -EntryName $entryName -Lines $lines -MatchIndex $i -Rule "FieldOrTableReference:$term" -Before 8 -After 14))
                        }

                        $isMutation = $line -match '(?i)(VALIDATE\s*\(|:=|MODIFY\s*\(|INSERT\s*\(|TRANSFERFIELDS\s*\()'
                        if ($isMutation -and $entryName -ne $pagePath) {
                            $populationContexts.Add((New-SourceContext -EntryName $entryName -Lines $lines -MatchIndex $i -Rule "PossiblePopulation:$term" -Before 14 -After 22))
                        }
                        elseif ($entryName -eq $pagePath) {
                            $consumerContexts.Add((New-SourceContext -EntryName $entryName -Lines $lines -MatchIndex $i -Rule "CustomerItemSalesListConsumer:$term" -Before 10 -After 16))
                        }
                    }
                }
            }
        }

        $result = [ordered]@{
            success = $true
            mode = 'GET_ONLY_BOYER_ITEM_PARAM_SOURCE_TRACE'
            environment = $Environment
            environmentType = $environmentType
            company = $CompanyName
            targetExtension = "$BoyerAppName $BoyerVersion"
            packageSha256 = (Get-FileHash -Path $packagePath -Algorithm SHA256).Hash
            navxSignature = 'NAVX'
            embeddedZipOffset = $zipOffset
            sourceFileCount = $source.Count
            customerItemSalesListPage = $pagePath
            itemParamRecordNames = @($itemParamRecordNames)
            itemParamTableIds = @($tableIds)
            itemParamDeclarations = @($itemParamDeclarations)
            tableDefinitions = @($tableDefinitions)
            fieldDefinitionContexts = @($fieldDefinitionContexts)
            populationContexts = @($populationContexts)
            consumerContexts = @($consumerContexts)
            counts = [ordered]@{
                itemParamRecordNames = $itemParamRecordNames.Count
                tableIds = $tableIds.Count
                tableDefinitions = $tableDefinitions.Count
                fieldDefinitionContexts = $fieldDefinitionContexts.Count
                populationContexts = $populationContexts.Count
                consumerContexts = $consumerContexts.Count
            }
            nextDecision = 'If the ItemParam table and fields are identified, create a read-only GPI Order Intake diagnostic API for that exact table and query only GIOVANN + C-503003-12033922. No Sales Order write is required.'
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
        Write-Host 'GPI ORDER INTAKE BOYER ITEM PARAMETER SOURCE TRACE: GET-ONLY PASS' -ForegroundColor Green
    }
    finally {
        $zip.Dispose()
        $memory.Dispose()
    }
}
finally {
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
