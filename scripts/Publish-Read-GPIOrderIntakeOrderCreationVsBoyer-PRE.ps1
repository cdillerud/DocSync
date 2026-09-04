#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY / ORDER-CREATION VS BOYER ROLLING-STATE DIAGNOSTIC
# Extension mutation is limited to GPI Order Intake 0.1.0.5 -> 0.1.0.6 in exact PRE.
# Reads exact Giovanni/item Sales Lines and posted Sales Invoice Line history only. No Sales Order action or business writes.
# =====================================================================================================================
$TenantId     = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment  = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName  = 'Gamer Packaging'
$CompanyId    = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv = 'Sandbox_NoZetadocs_UAT'
$EnableFlag   = 'GPI_ORDER_INTAKE_ORDER_CREATION_DIAGNOSTIC_DEPLOY_ENABLED'

$GpiAppId       = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$GpiAppName     = 'GPI Order Intake'
$GpiPublisher   = 'Gamer Packaging Inc'
$FromVersion    = '0.1.0.5'
$TargetVersion  = '0.1.0.6'

$BoyerAppId     = '65994cd5-4d6f-497e-abc0-767b8c392608'
$BoyerAppName   = 'Boyer And Associates Custom Package'
$BoyerPublisher = 'Boyer And Associates'
$BoyerVersion   = '25.0.0.13'
$BoyerHash      = '3B514699E7DA387B480436C850652555D8BC5E6564A47DA7A1690B59D93EF7E5'

$CustomerNumber = 'GIOVANN'
$ItemNumber     = 'C-503003-12033922'

$RepoRoot    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ProjectPath = Join-Path $RepoRoot 'order-intake-bc'
$BuildScript = Join-Path $PSScriptRoot 'Build-GPIOrderIntakeAL.ps1'
$PackagePath = Join-Path $ProjectPath '.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.6.app'

function Convert-TokenToString {
    param([Parameter(Mandatory)]$TokenValue)
    if ($TokenValue -is [string]) { return $TokenValue }
    if ($TokenValue -is [Security.SecureString]) { return [System.Net.NetworkCredential]::new('', $TokenValue).Password }
    if ($TokenValue.PSObject.Properties.Name -contains 'SecurePassword') {
        return [System.Net.NetworkCredential]::new('', $TokenValue.SecurePassword).Password
    }
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
    if ($Uri.IndexOf($ForbiddenEnv, [StringComparison]::OrdinalIgnoreCase) -ge 0) { throw 'Forbidden legacy sandbox URI blocked.' }
    if ($Uri.IndexOf('/Production/', [StringComparison]::OrdinalIgnoreCase) -ge 0) { throw 'Production URI blocked.' }
}

function Invoke-BcGet {
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers)
    Assert-BcUri $Uri
    Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 90
}

function Invoke-BcPost {
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers,[object]$Body)
    Assert-BcUri $Uri
    if ($null -eq $Body) {
        return Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -ContentType 'application/json' -TimeoutSec 90
    }
    Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -Body ($Body | ConvertTo-Json -Depth 20) -ContentType 'application/json' -TimeoutSec 90
}

function Get-InstalledVersionString {
    param([Parameter(Mandatory)]$Extension)
    "$($Extension.versionMajor).$($Extension.versionMinor).$($Extension.versionBuild).$($Extension.versionRevision)"
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    $Value.Replace("'", "''")
}

function Get-SymbolMajorVersion {
    param([Parameter(Mandatory)][string]$Directory,[Parameter(Mandatory)][string]$PackageStem)
    $m = @(Get-ChildItem $Directory -Filter "Microsoft_${PackageStem}_*.app" -File -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -match '^Microsoft_.+?_(\d+)\.(\d+)(?:\.|_)') {
            [pscustomobject]@{ File=$_.FullName; Major=[int]$Matches[1]; Minor=[int]$Matches[2] }
        }
    } | Sort-Object @{Expression='Major';Descending=$true}, @{Expression='Minor';Descending=$true})
    if ($m.Length -eq 0) { return $null }
    $m[0]
}

function Test-CompatibleMicrosoftCache {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path $Path -PathType Container)) { return $false }
    $a = Get-SymbolMajorVersion $Path 'Application'
    $b = Get-SymbolMajorVersion $Path 'Base Application'
    $s = Get-SymbolMajorVersion $Path 'System Application'
    $y = Get-SymbolMajorVersion $Path 'System'
    if ($null -eq $a -or $null -eq $b -or $null -eq $s -or $null -eq $y) { return $false }
    ($a.Major -ge 24 -and $b.Major -ge 24 -and $s.Major -ge 24 -and $y.Major -ge 24)
}

# Hard pins before BC mutation.
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831' -or $Environment -match '(?i)prod|production') { throw 'Environment pin changed/forbidden.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company pin changed.' }
if ($CustomerNumber -ne 'GIOVANN' -or $ItemNumber -ne 'C-503003-12033922') { throw 'Diagnostic customer/item pin changed.' }
if ([Environment]::GetEnvironmentVariable($EnableFlag) -ine 'true') { throw "Set `$env:$EnableFlag = 'true' explicitly." }
if (-not (Test-Path $BuildScript)) { throw "Build script missing: $BuildScript" }

$token = Get-BcToken
$headers = @{ Authorization="Bearer $token"; Accept='application/json' }
$envs = Invoke-BcGet 'https://api.businesscentral.dynamics.com/environments/v1.2' $headers
$envMatch = @($envs.value | Where-Object { [string]$_.name -eq $Environment })
if ($envMatch.Length -ne 1 -or [string]$envMatch[0].type -ine 'sandbox') { throw 'Exact PRE sandbox verification failed.' }
$environmentType = [string]$envMatch[0].type

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet "$standardRoot/companies" $headers
$companyMatch = @($companies.value | Where-Object { [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName)) })
if ($companyMatch.Length -ne 1) { throw 'Exact Gamer Packaging company verification failed.' }

$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"
$extensions = Invoke-BcGet "$automationRoot/extensions?`$top=500" $headers
$installed = @($extensions.value | Where-Object { $_.isInstalled -eq $true })
$boyer = @($installed | Where-Object { [string]$_.id -eq $BoyerAppId -and [string]$_.displayName -eq $BoyerAppName -and [string]$_.publisher -eq $BoyerPublisher -and (Get-InstalledVersionString $_) -eq $BoyerVersion })
if ($boyer.Length -ne 1) { throw 'Exact Boyer dependency is not installed.' }
$gpi = @($installed | Where-Object { [string]$_.id -eq $GpiAppId -and [string]$_.displayName -eq $GpiAppName -and [string]$_.publisher -eq $GpiPublisher })
if ($gpi.Length -ne 1) { throw 'Expected exactly one installed GPI Order Intake app.' }
$currentVersion = Get-InstalledVersionString $gpi[0]
if ($currentVersion -notin @($FromVersion,$TargetVersion)) { throw "Unexpected installed GPI version: $currentVersion" }

Write-Host ('='*120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - ORDER CREATION VS BOYER ROLLING STATE / PRE ONLY' -ForegroundColor Cyan
Write-Host ('='*120) -ForegroundColor Cyan
Write-Host "Environment        : $Environment"
Write-Host "Environment type   : $environmentType"
Write-Host "Company            : $CompanyName"
Write-Host "Installed GPI app  : $currentVersion"
Write-Host "Target GPI app     : $TargetVersion"
Write-Host "Customer / item    : $CustomerNumber / $ItemNumber"
Write-Host 'Business data read : EXACT OPEN SALES LINES + EXACT POSTED INVOICE HISTORY ONLY' -ForegroundColor Yellow
Write-Host 'Business data write: NONE' -ForegroundColor Green
Write-Host 'Sales-order action : NOT CALLED' -ForegroundColor Green
Write-Host 'Production         : HARD BLOCKED' -ForegroundColor Green
Write-Host ('='*120) -ForegroundColor Cyan

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('GPIOrderIntake-OrderCreation-' + [guid]::NewGuid().ToString('N'))
$tempCache = Join-Path $tempRoot 'alpackages'
[IO.Directory]::CreateDirectory($tempCache) | Out-Null

try {
    $deploymentPerformed = $false
    $packageHash = $null

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
        foreach ($c in $candidates) { if (Test-CompatibleMicrosoftCache $c) { $msCache=(Resolve-Path $c).Path; break } }
        if ([string]::IsNullOrWhiteSpace($msCache)) { throw 'No compatible Microsoft symbol cache found.' }
        foreach ($f in @(Get-ChildItem $msCache -Filter '*.app' -File)) { Copy-Item $f.FullName (Join-Path $tempCache $f.Name) -Force }

        $boyerPath = Join-Path $tempCache 'Boyer And Associates_Boyer And Associates Custom Package_25.0.0.13.app'
        $boyerUri = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/dev/packages?appId=$BoyerAppId&versionText=$BoyerVersion"
        Assert-BcUri $boyerUri
        Invoke-WebRequest -Method Get -Uri $boyerUri -Headers @{Authorization="Bearer $token"} -OutFile $boyerPath -TimeoutSec 120
        if ((Get-FileHash $boyerPath -Algorithm SHA256).Hash -ne $BoyerHash) { throw 'Boyer dependency package SHA changed.' }

        $rawBuild = Get-Content $BuildScript -Raw
        if (([regex]::Matches($rawBuild,[regex]::Escape('0.1.0.4'))).Count -lt 2) { throw 'Unexpected build-script version markers; refusing temporary patch.' }
        $patchedBuild = $rawBuild.Replace('0.1.0.4','0.1.0.6')
        $tempBuild = Join-Path $tempRoot 'Build-GPIOrderIntakeAL-0.1.0.6.ps1'
        Set-Content $tempBuild $patchedBuild -Encoding UTF8 -NoNewline
        & $tempBuild -ProjectPath $ProjectPath -PackageCachePath $tempCache
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "Compile failed: $LASTEXITCODE" }
        if (-not (Test-Path $PackagePath)) { throw "Compiled package missing: $PackagePath" }
        $packageHash = (Get-FileHash $PackagePath -Algorithm SHA256).Hash

        Write-Host "Compiled package SHA256: $packageHash" -ForegroundColor Green
        $upload = Invoke-BcPost "$automationRoot/extensionUpload" $headers ([ordered]@{schedule='Current version';schemaSyncMode='Add'})
        $uploadId = [string]$upload.systemId
        if ([string]::IsNullOrWhiteSpace($uploadId)) { throw 'extensionUpload did not return systemId.' }
        $contentUri = "$automationRoot/extensionUpload($uploadId)/extensionContent"
        Assert-BcUri $contentUri
        $patchResult = Invoke-WebRequest -Method Patch -Uri $contentUri -Headers @{Authorization="Bearer $token";Accept='application/json';'If-Match'='*'} -ContentType 'application/octet-stream' -InFile $PackagePath -SkipHttpErrorCheck -TimeoutSec 180
        if ([int]$patchResult.StatusCode -lt 200 -or [int]$patchResult.StatusCode -ge 300) { throw "Package upload failed HTTP $($patchResult.StatusCode)." }
        $started = [DateTimeOffset]::UtcNow.AddSeconds(-15)
        $null = Invoke-BcPost "$automationRoot/extensionUpload($uploadId)/Microsoft.NAV.upload" $headers $null
        $done=$false
        for ($i=1;$i -le 90;$i++) {
            Start-Sleep -Seconds 2
            $statuses=Invoke-BcGet "$automationRoot/extensionDeploymentStatus?`$top=200" $headers
            $m=@($statuses.value | Where-Object { [string]$_.name -eq $GpiAppName -and [string]$_.publisher -eq $GpiPublisher -and [string]$_.appVersion -eq $TargetVersion -and ([DateTimeOffset]$_.startedOn) -ge $started } | Sort-Object {[DateTimeOffset]$_.startedOn} -Descending)
            if ($m.Length -eq 0) { continue }
            $status=[string]$m[0].status
            Write-Host "Deployment status: $status" -ForegroundColor Yellow
            if ($status -match '(?i)fail|error|cancel') { throw "Deployment failed: $status" }
            if ($status -match '(?i)complete|success') { $done=$true; $deploymentPerformed=$true; break }
        }
        if (-not $done) { throw 'Timed out waiting for 0.1.0.6 deployment.' }
    }
    else {
        Write-Host 'GPI Order Intake 0.1.0.6 already installed; skipping duplicate deployment.' -ForegroundColor Green
    }

    $after=Invoke-BcGet "$automationRoot/extensions?`$top=500" $headers
    $exact=@($after.value | Where-Object { [string]$_.id -eq $GpiAppId -and [string]$_.displayName -eq $GpiAppName -and [string]$_.publisher -eq $GpiPublisher -and $_.isInstalled -eq $true -and (Get-InstalledVersionString $_) -eq $TargetVersion })
    if ($exact.Length -ne 1) { throw 'PRE 0.1.0.6 extension verification failed.' }
    Write-Host 'PRE 0.1.0.6 extension verification: PASS' -ForegroundColor Green

    $cust = Escape-ODataLiteral $CustomerNumber
    $item = Escape-ODataLiteral $ItemNumber
    $filter = [Uri]::EscapeDataString("sellToCustomerNumber eq '$cust' and itemNumber eq '$item'")
    $lineUri = "$customRoot/orderIntakeLines?`$filter=$filter&`$top=200"
    $invoiceUri = "$customRoot/orderIntakePostedInvoiceLines?`$filter=$filter&`$top=500"

    $lines = @((Invoke-BcGet $lineUri $headers).value | Sort-Object {[DateTimeOffset]$_.systemCreatedAt})
    $invoices = @((Invoke-BcGet $invoiceUri $headers).value | Sort-Object {[DateTimeOffset]$_.systemCreatedAt})

    $comparisons = [System.Collections.Generic.List[object]]::new()
    foreach ($line in $lines) {
        $created=[DateTimeOffset]$line.systemCreatedAt
        $prior=@($invoices | Where-Object { ([DateTimeOffset]$_.systemCreatedAt) -le $created } | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
        $p = if ($prior.Length -gt 0) { $prior[0] } else { $null }
        $modifiedAfterCreation = ([DateTimeOffset]$line.systemModifiedAt) -gt $created.AddSeconds(1)
        $matches=$false
        if ($null -ne $p) {
            $matches = ([decimal]$line.quantity -eq [decimal]$p.quantity -and [string]$line.unitOfMeasureCode -eq [string]$p.unitOfMeasureCode -and [decimal]$line.unitPrice -eq [decimal]$p.unitPrice -and [string]$line.locationCode -eq [string]$p.locationCode)
        }
        $comparisons.Add([pscustomobject][ordered]@{
            documentNumber = $line.documentNumber
            sequence = $line.sequence
            shipmentDate = $line.shipmentDate
            systemCreatedAt = $line.systemCreatedAt
            systemCreatedBy = $line.systemCreatedBy
            systemModifiedAt = $line.systemModifiedAt
            systemModifiedBy = $line.systemModifiedBy
            modifiedAfterCreation = $modifiedAfterCreation
            currentQuantity = $line.quantity
            currentUom = $line.unitOfMeasureCode
            currentUnitPrice = $line.unitPrice
            currentLocation = $line.locationCode
            priorPostedInvoiceDocument = if ($null -ne $p) { $p.documentNumber } else { $null }
            priorPostedInvoiceCreatedAt = if ($null -ne $p) { $p.systemCreatedAt } else { $null }
            priorRollingQuantity = if ($null -ne $p) { $p.quantity } else { $null }
            priorRollingUom = if ($null -ne $p) { $p.unitOfMeasureCode } else { $null }
            priorRollingUnitPrice = if ($null -ne $p) { $p.unitPrice } else { $null }
            priorRollingLocation = if ($null -ne $p) { $p.locationCode } else { $null }
            currentLineMatchesPriorRollingState = $matches
        })
    }

    $matching=@($comparisons | Where-Object { $_.currentLineMatchesPriorRollingState -eq $true })
    $unmodifiedMatching=@($comparisons | Where-Object { $_.currentLineMatchesPriorRollingState -eq $true -and $_.modifiedAfterCreation -eq $false })
    $result=[ordered]@{
        success=$true
        mode='PRE_ORDER_CREATION_VS_BOYER_ROLLING_STATE'
        environment=$Environment
        environmentType=$environmentType
        company=$CompanyName
        gpiOrderIntakeVersion=$TargetVersion
        boyerVersion=$BoyerVersion
        deploymentPerformed=$deploymentPerformed
        compiledPackageSha256=$packageHash
        query=[ordered]@{sellToCustomerNumber=$CustomerNumber;itemNumber=$ItemNumber}
        openSalesLineCount=$lines.Length
        postedInvoiceHistoryCount=$invoices.Length
        matchingPriorRollingStateCount=$matching.Length
        unmodifiedMatchingPriorRollingStateCount=$unmodifiedMatching.Length
        comparisons=@($comparisons)
        interpretation='A match means the current Sales Line quantity/UOM/price/location equals the last qualifying posted invoice state that existed when the Sales Line was created. modifiedAfterCreation=true means later edits remain possible, so current values are not guaranteed to be original insert values.'
        safety=[ordered]@{extensionMutation=if($deploymentPerformed){'GPI ORDER INTAKE 0.1.0.5 -> 0.1.0.6 IN EXACT PRE ONLY'}else{'NONE - TARGET VERSION ALREADY INSTALLED'};businessDataRead='EXACT GIOVANN ITEM SALES LINES + POSTED INVOICE HISTORY ONLY';businessDataWrites='NONE';salesOrderAction='NOT CALLED';production='HARD BLOCKED'}
    }
    $result | ConvertTo-Json -Depth 20
    Write-Host ''
    Write-Host 'GPI ORDER INTAKE ORDER CREATION VS BOYER ROLLING STATE DIAGNOSTIC: PASS' -ForegroundColor Green
}
finally {
    Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
