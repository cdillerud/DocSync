#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY / EXACT CUSTOMER+ITEM / READ-ONLY BUSINESS-DATA DIAGNOSTIC
# Extension mutation is limited to upgrading GPI Order Intake 0.1.0.3 -> 0.1.0.4 in the exact PRE sandbox.
# No Sales Order action is called. No business data is written.
# =====================================================================================================================
$TenantId     = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment  = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName  = 'Gamer Packaging'
$CompanyId    = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv = 'Sandbox_NoZetadocs_UAT'
$EnableFlag   = 'GPI_ORDER_INTAKE_CUSTOMER_ITEM_SALES_DIAGNOSTIC_DEPLOY_ENABLED'

$GpiAppId        = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$GpiAppName      = 'GPI Order Intake'
$GpiPublisher    = 'Gamer Packaging Inc'
$FromVersion     = '0.1.0.3'
$TargetVersion   = '0.1.0.4'

$BoyerAppId      = '65994cd5-4d6f-497e-abc0-767b8c392608'
$BoyerAppName    = 'Boyer And Associates Custom Package'
$BoyerPublisher  = 'Boyer And Associates'
$BoyerVersion    = '25.0.0.13'

$CustomerNumber  = 'GIOVANN'
$ItemNumber      = 'C-503003-12033922'
$ExpectedQty      = [decimal]56.42
$ExpectedUom      = 'M'
$ExpectedPrice    = [decimal]277.99
$ExpectedLocation = '00'

$RepoRoot     = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ProjectPath  = Join-Path $RepoRoot 'order-intake-bc'
$BuildScript  = Join-Path $PSScriptRoot 'Build-GPIOrderIntakeAL.ps1'
$PackagePath  = Join-Path $ProjectPath '.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.4.app'

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

function Invoke-BcPost {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][hashtable]$Headers,
        [object]$Body
    )
    Assert-BcUri $Uri
    if ($null -eq $Body) {
        return Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -ContentType 'application/json' -TimeoutSec 90
    }
    Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -Body ($Body | ConvertTo-Json -Depth 20) -ContentType 'application/json' -TimeoutSec 90
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    return $Value.Replace("'", "''")
}

function Get-InstalledVersionString {
    param([Parameter(Mandatory)]$Extension)
    return "$($Extension.versionMajor).$($Extension.versionMinor).$($Extension.versionBuild).$($Extension.versionRevision)"
}

function Get-SymbolMajorVersion {
    param(
        [Parameter(Mandatory)][string]$Directory,
        [Parameter(Mandatory)][string]$PackageStem
    )
    $matches = @(Get-ChildItem $Directory -Filter "Microsoft_${PackageStem}_*.app" -File -ErrorAction SilentlyContinue |
        ForEach-Object {
            if ($_.Name -match '^Microsoft_.+?_(\d+)\.(\d+)(?:\.|_)') {
                [pscustomobject]@{ File = $_.FullName; Major = [int]$Matches[1]; Minor = [int]$Matches[2] }
            }
        } |
        Sort-Object @{ Expression = 'Major'; Descending = $true }, @{ Expression = 'Minor'; Descending = $true })
    if ($matches.Length -eq 0) { return $null }
    return $matches[0]
}

function Test-CompatibleMicrosoftCache {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path $Path -PathType Container)) { return $false }
    $application = Get-SymbolMajorVersion -Directory $Path -PackageStem 'Application'
    $baseApp = Get-SymbolMajorVersion -Directory $Path -PackageStem 'Base Application'
    $systemApp = Get-SymbolMajorVersion -Directory $Path -PackageStem 'System Application'
    $system = Get-SymbolMajorVersion -Directory $Path -PackageStem 'System'
    if ($null -eq $application -or $null -eq $baseApp -or $null -eq $systemApp -or $null -eq $system) { return $false }
    return ($application.Major -ge 24 -and $baseApp.Major -ge 24 -and $systemApp.Major -ge 24 -and $system.Major -ge 24)
}

# ---------------------------------------------------------------------------------------------------------------------
# Fail closed before any BC or filesystem mutation beyond temp/cache preparation.
# ---------------------------------------------------------------------------------------------------------------------
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }
if ($CustomerNumber -ne 'GIOVANN' -or $ItemNumber -ne 'C-503003-12033922') { throw 'Diagnostic customer/item hard pin changed.' }
if ([Environment]::GetEnvironmentVariable($EnableFlag) -ine 'true') {
    throw "REFUSING DIAGNOSTIC DEPLOY: set `$env:$EnableFlag = 'true' explicitly for this PRE-only extension upgrade/read."
}
if (-not (Test-Path $BuildScript)) { throw "Build script not found: $BuildScript" }

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
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"

$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$installedExtensions = @($extensions.value | Where-Object { $_.isInstalled -eq $true })

$boyerMatches = @($installedExtensions | Where-Object {
    [string]$_.id -eq $BoyerAppId -and
    [string]$_.displayName -eq $BoyerAppName -and
    [string]$_.publisher -eq $BoyerPublisher -and
    (Get-InstalledVersionString -Extension $_) -eq $BoyerVersion
})
if ($boyerMatches.Length -ne 1) { throw "Expected exactly one installed $BoyerAppName $BoyerVersion; found $($boyerMatches.Length)." }

$gpiInstalled = @($installedExtensions | Where-Object {
    [string]$_.id -eq $GpiAppId -and [string]$_.displayName -eq $GpiAppName -and [string]$_.publisher -eq $GpiPublisher
})
if ($gpiInstalled.Length -ne 1) { throw "Expected exactly one installed $GpiAppName; found $($gpiInstalled.Length)." }
$currentGpiVersion = Get-InstalledVersionString -Extension $gpiInstalled[0]
if ($currentGpiVersion -notin @($FromVersion, $TargetVersion)) {
    throw "Unexpected installed $GpiAppName version '$currentGpiVersion'. Expected only $FromVersion or $TargetVersion."
}

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - CUSTOMER ITEM SALES DIAGNOSTIC / PRE ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment        : $Environment"
Write-Host "Environment type   : $environmentType"
Write-Host "Company            : $CompanyName"
Write-Host "Company ID         : $CompanyId"
Write-Host "Installed GPI app  : $GpiAppName $currentGpiVersion"
Write-Host "Target GPI app     : $TargetVersion"
Write-Host "Boyer dependency   : $BoyerAppName $BoyerVersion"
Write-Host "Diagnostic customer: $CustomerNumber"
Write-Host "Diagnostic item    : $ItemNumber"
Write-Host 'Business data read : EXACT CUSTOMER ITEM SALES ROW ONLY' -ForegroundColor Yellow
Write-Host 'Business data write: NONE' -ForegroundColor Green
Write-Host 'Sales-order action : NOT CALLED' -ForegroundColor Green
Write-Host 'Release/Ship/Post  : NOT IMPLEMENTED / BLOCKED' -ForegroundColor Green
Write-Host 'Production         : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("GPIOrderIntake-CustomerItemSales-" + [Guid]::NewGuid().ToString('N'))
$tempCache = Join-Path $tempRoot 'alpackages'
[System.IO.Directory]::CreateDirectory($tempCache) | Out-Null

try {
    $deploymentPerformed = $false
    $packageHash = $null

    if ($currentGpiVersion -eq $FromVersion) {
        # Locate a read-only Microsoft symbol cache and copy symbols into an isolated temp cache.
        $documents = [Environment]::GetFolderPath('MyDocuments')
        $knownCandidates = @(
            (Join-Path $ProjectPath '.alpackages'),
            (Join-Path $RepoRoot 'bc-extension\.alpackages'),
            (Join-Path $RepoRoot 'packaging-catalog-bc\.alpackages'),
            (Join-Path $documents 'AL\MappingProj\.alpackages'),
            (Join-Path $documents 'DocSync-V69-CommercialFederation\packaging-catalog-bc\.alpackages'),
            (Join-Path $documents 'DocSync-PackagingCatalog\packaging-catalog-bc\.alpackages'),
            (Join-Path $documents 'DocSync-Zetadocs\bc-extension\zetadocs-replacement\.alpackages')
        )
        $microsoftCache = $null
        foreach ($candidate in $knownCandidates) {
            if (Test-CompatibleMicrosoftCache -Path $candidate) {
                $microsoftCache = (Resolve-Path $candidate).Path
                break
            }
        }
        if ([string]::IsNullOrWhiteSpace($microsoftCache)) {
            throw 'Could not locate a complete Microsoft 24.x-or-newer AL symbol cache.'
        }

        Write-Host "Copying Microsoft symbols from: $microsoftCache" -ForegroundColor Yellow
        $symbolFiles = @(Get-ChildItem $microsoftCache -Filter '*.app' -File)
        if ($symbolFiles.Length -eq 0) { throw "No .app symbols found in $microsoftCache" }
        foreach ($symbol in $symbolFiles) {
            Copy-Item -LiteralPath $symbol.FullName -Destination (Join-Path $tempCache $symbol.Name) -Force
        }

        # Download the exact installed Boyer dependency package by GET only.
        $boyerPackagePath = Join-Path $tempCache 'Boyer And Associates_Boyer And Associates Custom Package_25.0.0.13.app'
        $symbolUri = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/dev/packages?appId=$BoyerAppId&versionText=$BoyerVersion"
        Assert-BcUri $symbolUri
        Write-Host 'Downloading exact Boyer 25.0.0.13 dependency symbol package (GET only)...' -ForegroundColor Yellow
        Invoke-WebRequest -Method Get -Uri $symbolUri -Headers @{ Authorization = "Bearer $token" } -OutFile $boyerPackagePath -TimeoutSec 120
        if (-not (Test-Path $boyerPackagePath) -or (Get-Item $boyerPackagePath).Length -le 0) {
            throw 'Boyer dependency package download failed.'
        }
        $boyerHash = (Get-FileHash $boyerPackagePath -Algorithm SHA256).Hash
        if ($boyerHash -ne '3B514699E7DA387B480436C850652555D8BC5E6564A47DA7A1690B59D93EF7E5') {
            throw "Boyer package SHA256 changed. Expected 3B514699E7DA387B480436C850652555D8BC5E6564A47DA7A1690B59D93EF7E5; got $boyerHash."
        }
        Write-Host "Boyer dependency SHA256: $boyerHash" -ForegroundColor Green

        # Compile 0.1.0.4 using only the isolated symbol cache. Build script does not contact BC.
        & $BuildScript -ProjectPath $ProjectPath -PackageCachePath $tempCache
        if (-not (Test-Path $PackagePath)) { throw "Expected compiled package not found: $PackagePath" }
        $packageHash = (Get-FileHash $PackagePath -Algorithm SHA256).Hash
        Write-Host "Compiled 0.1.0.4 SHA256: $packageHash" -ForegroundColor Green

        # Re-hash immediately before upload so the compiled artifact cannot change between validation and mutation.
        $preUploadHash = (Get-FileHash $PackagePath -Algorithm SHA256).Hash
        if ($preUploadHash -ne $packageHash) { throw 'Compiled package changed before upload. Stopping.' }

        Write-Host 'Creating PRE 0.1.0.4 extension-upload record...' -ForegroundColor Yellow
        $uploadRecord = Invoke-BcPost -Uri "$automationRoot/extensionUpload" -Headers $headers -Body ([ordered]@{
            schedule = 'Current version'
            schemaSyncMode = 'Add'
        })
        $uploadId = [string]$uploadRecord.systemId
        if ([string]::IsNullOrWhiteSpace($uploadId)) { throw 'extensionUpload did not return systemId.' }

        $contentUri = "$automationRoot/extensionUpload($uploadId)/extensionContent"
        Assert-BcUri $contentUri
        $binaryHeaders = @{ Authorization = "Bearer $token"; Accept = 'application/json'; 'If-Match' = '*' }
        Write-Host "Uploading exact compiled 0.1.0.4 package to PRE upload record $uploadId..." -ForegroundColor Yellow
        $patch = Invoke-WebRequest -Method Patch -Uri $contentUri -Headers $binaryHeaders -ContentType 'application/octet-stream' -InFile $PackagePath -SkipHttpErrorCheck -TimeoutSec 180
        if ([int]$patch.StatusCode -lt 200 -or [int]$patch.StatusCode -ge 300) {
            throw "Extension content upload failed: HTTP $($patch.StatusCode) $($patch.Content)"
        }

        $postUploadHash = (Get-FileHash $PackagePath -Algorithm SHA256).Hash
        if ($postUploadHash -ne $packageHash) { throw 'Compiled package changed during upload. Stopping.' }

        $deploymentStart = [DateTimeOffset]::UtcNow.AddSeconds(-15)
        Write-Host 'Starting PRE 0.1.0.4 extension deployment...' -ForegroundColor Yellow
        $null = Invoke-BcPost -Uri "$automationRoot/extensionUpload($uploadId)/Microsoft.NAV.upload" -Headers $headers

        $completed = $false
        for ($attempt = 1; $attempt -le 90; $attempt++) {
            Start-Sleep -Seconds 2
            $statuses = Invoke-BcGet -Uri "$automationRoot/extensionDeploymentStatus?`$top=200" -Headers $headers
            $matches = @($statuses.value | Where-Object {
                [string]$_.name -eq $GpiAppName -and
                [string]$_.publisher -eq $GpiPublisher -and
                [string]$_.appVersion -eq $TargetVersion -and
                ([DateTimeOffset]$_.startedOn) -ge $deploymentStart
            } | Sort-Object { [DateTimeOffset]$_.startedOn } -Descending)
            if ($matches.Length -eq 0) { continue }
            $latest = $matches[0]
            Write-Host "Deployment status: $($latest.status)" -ForegroundColor Yellow
            if ([string]$latest.status -match '(?i)fail|error|cancel') {
                throw "$GpiAppName $TargetVersion deployment failed with status '$($latest.status)'."
            }
            if ([string]$latest.status -match '(?i)complete|success') {
                $completed = $true
                $deploymentPerformed = $true
                break
            }
        }
        if (-not $completed) { throw "Timed out waiting for $GpiAppName $TargetVersion deployment." }
    }
    else {
        Write-Host "$GpiAppName $TargetVersion is already installed; skipping duplicate deployment." -ForegroundColor Green
    }

    # Verify exact target app and Boyer dependency still installed after deployment.
    $extensionsAfter = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
    $installedAfter = @($extensionsAfter.value | Where-Object { $_.isInstalled -eq $true })
    $gpiAfter = @($installedAfter | Where-Object {
        [string]$_.id -eq $GpiAppId -and [string]$_.displayName -eq $GpiAppName -and [string]$_.publisher -eq $GpiPublisher -and
        (Get-InstalledVersionString -Extension $_) -eq $TargetVersion
    })
    if ($gpiAfter.Length -ne 1) { throw "Expected exactly one installed $GpiAppName $TargetVersion after deployment; found $($gpiAfter.Length)." }
    $boyerAfter = @($installedAfter | Where-Object {
        [string]$_.id -eq $BoyerAppId -and [string]$_.displayName -eq $BoyerAppName -and [string]$_.publisher -eq $BoyerPublisher -and
        (Get-InstalledVersionString -Extension $_) -eq $BoyerVersion
    })
    if ($boyerAfter.Length -ne 1) { throw "Boyer dependency verification failed after deployment; found $($boyerAfter.Length)." }
    Write-Host 'PRE extension verification: PASS' -ForegroundColor Green

    # Exact GET-only business-data read. No Sales Order action exists in this path.
    $customerLiteral = Escape-ODataLiteral $CustomerNumber
    $itemLiteral = Escape-ODataLiteral $ItemNumber
    $filter = [Uri]::EscapeDataString("sellToCustomerNumber eq '$customerLiteral' and itemNumber eq '$itemLiteral'")
    $readUri = "$customRoot/orderIntakeCustomerItemSales?`$filter=$filter&`$top=2"

    $response = $null
    for ($attempt = 1; $attempt -le 45; $attempt++) {
        try {
            $response = Invoke-BcGet -Uri $readUri -Headers $headers
            break
        }
        catch {
            if ($attempt -eq 45) { throw }
            Start-Sleep -Seconds 2
        }
    }

    $rows = @($response.value)
    if ($rows.Length -gt 1) { throw "Primary-key diagnostic returned more than one row: $($rows.Length)." }

    $rowFound = $rows.Length -eq 1
    $row = if ($rowFound) { $rows[0] } else { $null }
    $quantityMatch = $false
    $uomMatch = $false
    $priceMatch = $false
    $locationMatch = $false
    if ($rowFound) {
        $quantityMatch = ([decimal]$row.lastSoldQuantity -eq $ExpectedQty)
        $uomMatch = ([string]$row.lastSoldUnitOfMeasureCode -eq $ExpectedUom)
        $priceMatch = ([decimal]$row.lastUnitPrice -eq $ExpectedPrice)
        $locationMatch = ([string]$row.locationCode -eq $ExpectedLocation)
    }
    $allObservedMatch = $rowFound -and $quantityMatch -and $uomMatch -and $priceMatch -and $locationMatch

    $conclusion = if (-not $rowFound) {
        'NO_CUSTOMER_ITEM_SALES_ROW_FOUND_FOR_GIOVANN_ITEM'
    }
    elseif ($allObservedMatch) {
        'BOYER_CARRIED_FORWARD_CONTEXT_CONFIRMED_56_42_M_277_99_LOCATION_00'
    }
    else {
        'CUSTOMER_ITEM_SALES_ROW_FOUND_BUT_CURRENT_STORED_VALUES_DIFFER_FROM_OBSERVED_ORDER_EVIDENCE'
    }

    $result = [ordered]@{
        success = $true
        mode = 'PRE_CUSTOMER_ITEM_SALES_EXACT_READ'
        environment = $Environment
        environmentType = $environmentType
        company = $CompanyName
        gpiOrderIntakeVersion = $TargetVersion
        boyerVersion = $BoyerVersion
        deploymentPerformed = $deploymentPerformed
        compiledPackageSha256 = $packageHash
        query = [ordered]@{
            sellToCustomerNumber = $CustomerNumber
            itemNumber = $ItemNumber
            maxRows = 2
        }
        rowFound = $rowFound
        row = $row
        observedEvidenceComparison = [ordered]@{
            expectedLastSoldQuantity = $ExpectedQty
            quantityMatches = $quantityMatch
            expectedLastSoldUnitOfMeasureCode = $ExpectedUom
            uomMatches = $uomMatch
            expectedLastUnitPrice = $ExpectedPrice
            priceMatches = $priceMatch
            expectedLocationCode = $ExpectedLocation
            locationMatches = $locationMatch
            allObservedEvidenceMatches = $allObservedMatch
        }
        conclusion = $conclusion
        safety = [ordered]@{
            extensionMutation = if ($deploymentPerformed) { 'GPI ORDER INTAKE 0.1.0.4 UPGRADE ONLY' } else { 'NONE - TARGET VERSION ALREADY INSTALLED' }
            businessDataRead = 'CUSTOMER ITEM SALES EXACT GIOVANN + C-503003-12033922 ROW ONLY'
            businessDataWrites = 'NONE'
            salesOrderAction = 'NOT CALLED'
            releaseShipInvoicePost = 'NOT IMPLEMENTED / BLOCKED'
            production = 'HARD BLOCKED'
        }
    }

    $result | ConvertTo-Json -Depth 12
    Write-Host ''
    Write-Host 'GPI ORDER INTAKE CUSTOMER ITEM SALES DIAGNOSTIC: PASS' -ForegroundColor Green
}
finally {
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
