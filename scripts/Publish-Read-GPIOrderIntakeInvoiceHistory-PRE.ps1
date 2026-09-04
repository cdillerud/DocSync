#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$TenantId     = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment  = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName  = 'Gamer Packaging'
$CompanyId    = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv = 'Sandbox_NoZetadocs_UAT'
$EnableFlag   = 'GPI_ORDER_INTAKE_INVOICE_HISTORY_DIAGNOSTIC_DEPLOY_ENABLED'

$GpiAppId      = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$GpiAppName    = 'GPI Order Intake'
$GpiPublisher  = 'Gamer Packaging Inc'
$FromVersion   = '0.1.0.4'
$TargetVersion = '0.1.0.5'

$BoyerAppId     = '65994cd5-4d6f-497e-abc0-767b8c392608'
$BoyerAppName   = 'Boyer And Associates Custom Package'
$BoyerPublisher = 'Boyer And Associates'
$BoyerVersion   = '25.0.0.13'
$BoyerSha256    = '3B514699E7DA387B480436C850652555D8BC5E6564A47DA7A1690B59D93EF7E5'

$CustomerNumber = 'GIOVANN'
$ItemNumber     = 'C-503003-12033922'
$KnownPrice00   = [decimal]277.99
$KnownPrice082  = [decimal]289.49
$KnownQuantity  = [decimal]56.42
$KnownUom       = 'M'

$RepoRoot    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ProjectPath = Join-Path $RepoRoot 'order-intake-bc'
$BuildScript = Join-Path $PSScriptRoot 'Build-GPIOrderIntakeInvoiceHistoryAL.ps1'
$PackagePath = Join-Path $ProjectPath '.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.5.app'

function Convert-TokenToString {
    param([Parameter(Mandatory)]$TokenValue)
    if ($TokenValue -is [string]) { return $TokenValue }
    if ($TokenValue -is [Security.SecureString]) { return [System.Net.NetworkCredential]::new('', $TokenValue).Password }
    if ($TokenValue.PSObject.Properties.Name -contains 'SecurePassword') { return [System.Net.NetworkCredential]::new('', $TokenValue.SecurePassword).Password }
    return [string]$TokenValue
}

function Get-BcToken {
    if (-not (Get-Module -ListAvailable -Name Az.Accounts)) { throw 'Az.Accounts is required.' }
    Import-Module Az.Accounts -ErrorAction Stop
    try {
        $r = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
        $t = Convert-TokenToString $r.Token
        if (-not [string]::IsNullOrWhiteSpace($t)) { return $t }
    }
    catch {}
    Write-Host 'Starting Business Central scoped Microsoft sign-in...' -ForegroundColor Yellow
    Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null
    Connect-AzAccount -Tenant $TenantId -AuthScope 'https://api.businesscentral.dynamics.com' -Scope Process -ErrorAction Stop | Out-Null
    $r = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
    $t = Convert-TokenToString $r.Token
    if ([string]::IsNullOrWhiteSpace($t)) { throw 'Could not acquire Business Central token.' }
    return $t
}

function Assert-BcUri {
    param([Parameter(Mandatory)][string]$Uri)
    $u = [Uri]$Uri
    if ($u.Scheme -ne 'https' -or $u.Host -ne 'api.businesscentral.dynamics.com') { throw "Unexpected BC URI blocked: $Uri" }
    if ($Uri.IndexOf($ForbiddenEnv, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { throw 'Forbidden legacy sandbox URI blocked.' }
    if ($Uri.IndexOf('/Production/', [System.StringComparison]::OrdinalIgnoreCase) -ge 0) { throw 'Production URI blocked.' }
}

function Invoke-BcGet {
    param([Parameter(Mandatory)][string]$Uri, [Parameter(Mandatory)][hashtable]$Headers)
    Assert-BcUri $Uri
    Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 90
}

function Invoke-BcPost {
    param([Parameter(Mandatory)][string]$Uri, [Parameter(Mandatory)][hashtable]$Headers, [object]$Body)
    Assert-BcUri $Uri
    if ($null -eq $Body) { return Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -ContentType 'application/json' -TimeoutSec 90 }
    Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -Body ($Body | ConvertTo-Json -Depth 20) -ContentType 'application/json' -TimeoutSec 90
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    return $Value.Replace("'", "''")
}

function Get-VersionString {
    param([Parameter(Mandatory)]$Extension)
    return "$($Extension.versionMajor).$($Extension.versionMinor).$($Extension.versionBuild).$($Extension.versionRevision)"
}

function Get-SymbolMajorVersion {
    param([Parameter(Mandatory)][string]$Directory, [Parameter(Mandatory)][string]$PackageStem)
    $m = @(Get-ChildItem $Directory -Filter "Microsoft_${PackageStem}_*.app" -File -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -match '^Microsoft_.+?_(\d+)\.(\d+)(?:\.|_)') { [pscustomobject]@{ File=$_.FullName; Major=[int]$Matches[1]; Minor=[int]$Matches[2] } }
    } | Sort-Object @{Expression='Major';Descending=$true}, @{Expression='Minor';Descending=$true})
    if ($m.Length -eq 0) { return $null }
    return $m[0]
}

function Test-CompatibleMicrosoftCache {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path $Path -PathType Container)) { return $false }
    $a = Get-SymbolMajorVersion $Path 'Application'
    $b = Get-SymbolMajorVersion $Path 'Base Application'
    $sa = Get-SymbolMajorVersion $Path 'System Application'
    $s = Get-SymbolMajorVersion $Path 'System'
    if ($null -eq $a -or $null -eq $b -or $null -eq $sa -or $null -eq $s) { return $false }
    return ($a.Major -ge 24 -and $b.Major -ge 24 -and $sa.Major -ge 24 -and $s.Major -ge 24)
}

if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }
if ($CustomerNumber -ne 'GIOVANN' -or $ItemNumber -ne 'C-503003-12033922') { throw 'Diagnostic customer/item hard pin changed.' }
if ([Environment]::GetEnvironmentVariable($EnableFlag) -ine 'true') { throw "REFUSING DIAGNOSTIC DEPLOY: set `$env:$EnableFlag = 'true'." }

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }
$envs = Invoke-BcGet 'https://api.businesscentral.dynamics.com/environments/v1.2' $headers
$envMatches = @($envs.value | Where-Object { [string]$_.name -eq $Environment })
if ($envMatches.Length -ne 1) { throw 'Exact PRE environment verification failed.' }
$environmentType = [string]$envMatches[0].type
if ($environmentType -ine 'sandbox') { throw "PRE environment type is '$environmentType', not sandbox." }

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet "$standardRoot/companies" $headers
$companyMatches = @($companies.value | Where-Object { [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName)) })
if ($companyMatches.Length -ne 1) { throw 'Exact Gamer Packaging company verification failed.' }

$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"
$extensions = Invoke-BcGet "$automationRoot/extensions?`$top=500" $headers
$installed = @($extensions.value | Where-Object { $_.isInstalled -eq $true })
$boyer = @($installed | Where-Object { [string]$_.id -eq $BoyerAppId -and [string]$_.displayName -eq $BoyerAppName -and [string]$_.publisher -eq $BoyerPublisher -and (Get-VersionString $_) -eq $BoyerVersion })
if ($boyer.Length -ne 1) { throw 'Exact Boyer 25.0.0.13 installation verification failed.' }
$gpi = @($installed | Where-Object { [string]$_.id -eq $GpiAppId -and [string]$_.displayName -eq $GpiAppName -and [string]$_.publisher -eq $GpiPublisher })
if ($gpi.Length -ne 1) { throw 'Exact GPI Order Intake installation verification failed.' }
$currentVersion = Get-VersionString $gpi[0]
if ($currentVersion -notin @($FromVersion,$TargetVersion)) { throw "Unexpected GPI Order Intake version: $currentVersion" }

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - POSTED INVOICE HISTORY / PRE ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment        : $Environment"
Write-Host "Environment type   : $environmentType"
Write-Host "Company            : $CompanyName"
Write-Host "Installed GPI app  : $currentVersion"
Write-Host "Target GPI app     : $TargetVersion"
Write-Host "Boyer dependency   : $BoyerVersion"
Write-Host "Customer           : $CustomerNumber"
Write-Host "Item               : $ItemNumber"
Write-Host 'Business data read : POSTED SALES INVOICE LINES + EXACT CUSTOMER ITEM SALES ROW' -ForegroundColor Yellow
Write-Host 'Business data write: NONE' -ForegroundColor Green
Write-Host 'Sales-order action : NOT CALLED' -ForegroundColor Green
Write-Host 'Production         : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("GPIOrderIntake-InvHist-" + [Guid]::NewGuid().ToString('N'))
$tempCache = Join-Path $tempRoot 'alpackages'
[System.IO.Directory]::CreateDirectory($tempCache) | Out-Null
$deploymentPerformed = $false
$packageHash = $null

try {
    if ($currentVersion -eq $FromVersion) {
        $documents = [Environment]::GetFolderPath('MyDocuments')
        $candidates = @(
            (Join-Path $ProjectPath '.alpackages'),
            (Join-Path $RepoRoot 'bc-extension\.alpackages'),
            (Join-Path $RepoRoot 'packaging-catalog-bc\.alpackages'),
            (Join-Path $documents 'AL\MappingProj\.alpackages'),
            (Join-Path $documents 'DocSync-V69-CommercialFederation\packaging-catalog-bc\.alpackages'),
            (Join-Path $documents 'DocSync-PackagingCatalog\packaging-catalog-bc\.alpackages'),
            (Join-Path $documents 'DocSync-Zetadocs\bc-extension\zetadocs-replacement\.alpackages')
        )
        $msCache = $null
        foreach ($c in $candidates) { if (Test-CompatibleMicrosoftCache $c) { $msCache = (Resolve-Path $c).Path; break } }
        if ([string]::IsNullOrWhiteSpace($msCache)) { throw 'Could not locate Microsoft AL symbol cache.' }
        foreach ($f in @(Get-ChildItem $msCache -Filter '*.app' -File)) { Copy-Item $f.FullName (Join-Path $tempCache $f.Name) -Force }

        $boyerPkg = Join-Path $tempCache 'Boyer And Associates_Boyer And Associates Custom Package_25.0.0.13.app'
        $boyerUri = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/dev/packages?appId=$BoyerAppId&versionText=$BoyerVersion"
        Assert-BcUri $boyerUri
        Invoke-WebRequest -Method Get -Uri $boyerUri -Headers @{ Authorization = "Bearer $token" } -OutFile $boyerPkg -TimeoutSec 120
        $actualBoyerHash = (Get-FileHash $boyerPkg -Algorithm SHA256).Hash
        if ($actualBoyerHash -ne $BoyerSha256) { throw "Boyer symbol SHA mismatch: $actualBoyerHash" }

        & $BuildScript -PackageCachePath $tempCache
        if (-not (Test-Path $PackagePath)) { throw '0.1.0.5 package was not created.' }
        $packageHash = (Get-FileHash $PackagePath -Algorithm SHA256).Hash

        $upload = Invoke-BcPost "$automationRoot/extensionUpload" $headers ([ordered]@{ schedule='Current version'; schemaSyncMode='Add' })
        $uploadId = [string]$upload.systemId
        if ([string]::IsNullOrWhiteSpace($uploadId)) { throw 'extensionUpload did not return systemId.' }
        $contentUri = "$automationRoot/extensionUpload($uploadId)/extensionContent"
        Assert-BcUri $contentUri
        $patch = Invoke-WebRequest -Method Patch -Uri $contentUri -Headers @{ Authorization="Bearer $token"; Accept='application/json'; 'If-Match'='*' } -ContentType 'application/octet-stream' -InFile $PackagePath -SkipHttpErrorCheck -TimeoutSec 180
        if ([int]$patch.StatusCode -lt 200 -or [int]$patch.StatusCode -ge 300) { throw "Extension content upload failed HTTP $($patch.StatusCode)." }
        $start = [DateTimeOffset]::UtcNow.AddSeconds(-15)
        $null = Invoke-BcPost "$automationRoot/extensionUpload($uploadId)/Microsoft.NAV.upload" $headers $null
        $complete = $false
        for ($i=1; $i -le 90; $i++) {
            Start-Sleep -Seconds 2
            $statuses = Invoke-BcGet "$automationRoot/extensionDeploymentStatus?`$top=200" $headers
            $matches = @($statuses.value | Where-Object { [string]$_.name -eq $GpiAppName -and [string]$_.publisher -eq $GpiPublisher -and [string]$_.appVersion -eq $TargetVersion -and ([DateTimeOffset]$_.startedOn) -ge $start } | Sort-Object { [DateTimeOffset]$_.startedOn } -Descending)
            if ($matches.Length -eq 0) { continue }
            $latest = $matches[0]
            Write-Host "Deployment status: $($latest.status)" -ForegroundColor Yellow
            if ([string]$latest.status -match '(?i)fail|error|cancel') { throw "Deployment failed: $($latest.status)" }
            if ([string]$latest.status -match '(?i)complete|success') { $complete=$true; $deploymentPerformed=$true; break }
        }
        if (-not $complete) { throw 'Timed out waiting for 0.1.0.5 deployment.' }
    }
    else {
        Write-Host 'GPI Order Intake 0.1.0.5 already installed; skipping duplicate deployment.' -ForegroundColor Green
    }

    $extensionsAfter = Invoke-BcGet "$automationRoot/extensions?`$top=500" $headers
    $gpiAfter = @($extensionsAfter.value | Where-Object { $_.isInstalled -eq $true -and [string]$_.id -eq $GpiAppId -and [string]$_.displayName -eq $GpiAppName -and [string]$_.publisher -eq $GpiPublisher -and (Get-VersionString $_) -eq $TargetVersion })
    if ($gpiAfter.Length -ne 1) { throw 'PRE 0.1.0.5 extension verification failed.' }
    Write-Host 'PRE 0.1.0.5 extension verification: PASS' -ForegroundColor Green

    $cust = Escape-ODataLiteral $CustomerNumber
    $item = Escape-ODataLiteral $ItemNumber
    $histFilter = [Uri]::EscapeDataString("sellToCustomerNumber eq '$cust' and itemNumber eq '$item'")
    $cisFilter = [Uri]::EscapeDataString("sellToCustomerNumber eq '$cust' and itemNumber eq '$item'")
    $history = Invoke-BcGet "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$histFilter&`$top=500" $headers
    $cis = Invoke-BcGet "$customRoot/orderIntakeCustomerItemSales?`$filter=$cisFilter&`$top=2" $headers

    $historyRows = @($history.value | Where-Object { [decimal]$_.quantity -gt 0 } | Sort-Object { [DateTimeOffset]$_.systemCreatedAt })
    $cisRows = @($cis.value)
    if ($cisRows.Length -gt 1) { throw 'Customer Item Sales returned more than one row for exact PK.' }
    $currentRow = if ($cisRows.Length -eq 1) { $cisRows[0] } else { $null }
    $latestHistory = if ($historyRows.Length -gt 0) { $historyRows[-1] } else { $null }

    $price00Rows = @($historyRows | Where-Object { [decimal]$_.quantity -eq $KnownQuantity -and [string]$_.unitOfMeasureCode -eq $KnownUom -and [decimal]$_.unitPrice -eq $KnownPrice00 -and [string]$_.locationCode -eq '00' })
    $price082Rows = @($historyRows | Where-Object { [decimal]$_.quantity -eq $KnownQuantity -and [string]$_.unitOfMeasureCode -eq $KnownUom -and [decimal]$_.unitPrice -eq $KnownPrice082 -and [string]$_.locationCode -eq '082' })

    $latestMatchesCurrent = $false
    if ($null -ne $latestHistory -and $null -ne $currentRow) {
        $latestMatchesCurrent = (
            [decimal]$latestHistory.quantity -eq [decimal]$currentRow.lastSoldQuantity -and
            [string]$latestHistory.unitOfMeasureCode -eq [string]$currentRow.lastSoldUnitOfMeasureCode -and
            [decimal]$latestHistory.unitPrice -eq [decimal]$currentRow.lastUnitPrice -and
            [string]$latestHistory.locationCode -eq [string]$currentRow.locationCode -and
            [string]$latestHistory.shipmentDate -eq [string]$currentRow.lastSoldDate
        )
    }

    $transitions = [System.Collections.Generic.List[object]]::new()
    for ($i=1; $i -lt $historyRows.Length; $i++) {
        $prev = $historyRows[$i-1]
        $cur = $historyRows[$i]
        if ([decimal]$prev.unitPrice -ne [decimal]$cur.unitPrice -or [string]$prev.locationCode -ne [string]$cur.locationCode) {
            $transitions.Add([pscustomobject][ordered]@{
                previousDocument = $prev.documentNumber
                previousShipmentDate = $prev.shipmentDate
                previousQuantity = $prev.quantity
                previousUom = $prev.unitOfMeasureCode
                previousUnitPrice = $prev.unitPrice
                previousLocation = $prev.locationCode
                nextDocument = $cur.documentNumber
                nextShipmentDate = $cur.shipmentDate
                nextQuantity = $cur.quantity
                nextUom = $cur.unitOfMeasureCode
                nextUnitPrice = $cur.unitPrice
                nextLocation = $cur.locationCode
            })
        }
    }

    $result = [ordered]@{
        success = $true
        mode = 'PRE_POSTED_INVOICE_HISTORY_EXACT_CUSTOMER_ITEM_READ'
        environment = $Environment
        environmentType = $environmentType
        company = $CompanyName
        gpiOrderIntakeVersion = $TargetVersion
        boyerVersion = $BoyerVersion
        deploymentPerformed = $deploymentPerformed
        compiledPackageSha256 = $packageHash
        query = [ordered]@{ sellToCustomerNumber=$CustomerNumber; itemNumber=$ItemNumber; maxRows=500 }
        historyCount = $historyRows.Length
        currentCustomerItemSalesRow = $currentRow
        latestPostedInvoiceLine = $latestHistory
        latestPostedInvoiceMatchesCurrentRollingState = $latestMatchesCurrent
        exact27799Location00Rows = $price00Rows
        exact28949Location082Rows = $price082Rows
        priceOrLocationTransitions = @($transitions)
        conclusion = if ($latestMatchesCurrent) { 'LATEST_POSTED_INVOICE_LINE_MATCHES_CURRENT_BOYER_ROLLING_STATE' } else { 'ROLLING_STATE_DOES_NOT_EXACTLY_MATCH_LATEST_RETURNED_POSTED_LINE_REVIEW_SEQUENCE' }
        safety = [ordered]@{
            extensionMutation = if ($deploymentPerformed) { 'GPI ORDER INTAKE 0.1.0.4 -> 0.1.0.5 ONLY' } else { 'NONE - TARGET VERSION ALREADY INSTALLED' }
            businessDataRead = 'EXACT GIOVANN + C-503003-12033922 POSTED INVOICE HISTORY AND CURRENT CUSTOMER ITEM SALES ROW'
            businessDataWrites = 'NONE'
            salesOrderAction = 'NOT CALLED'
            releaseShipInvoicePost = 'NOT IMPLEMENTED / BLOCKED'
            production = 'HARD BLOCKED'
        }
    }
    $result | ConvertTo-Json -Depth 12
    Write-Host ''
    Write-Host 'GPI ORDER INTAKE POSTED INVOICE HISTORY DIAGNOSTIC: PASS' -ForegroundColor Green
}
finally {
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
