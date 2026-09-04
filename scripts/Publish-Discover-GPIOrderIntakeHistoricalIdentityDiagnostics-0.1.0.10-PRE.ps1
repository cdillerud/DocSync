#requires -Version 7.0

[CmdletBinding()]
param(
    [switch]$EnableInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$CompanyId         = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'

$ExpectedAppId       = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$ExpectedAppName     = 'GPI Order Intake'
$ExpectedPublisher   = 'Gamer Packaging Inc'
$ExpectedAppVersion  = '0.1.0.10'
$ExpectedPackageHash = 'C398F0D44795FCF1111F8E4C32E9B94052CF96BA7900A4990DF91F66845BADB0'

$BernerCustomer   = 'BERNER'
$BernerOrder      = '114600'
$BernerSourcePo   = '241355'
$BernerSourceRef  = '811476'
$BernerItem       = '21759-858231'
$BernerShipToCode = '78899028'

$HerdezCustomer   = 'HERDEZ'
$HerdezSourcePo   = '4500063632'
$HerdezSourceRef  = '000000000004003467'
$HerdezItem       = '20113526'
$HerdezShipToCode = '001'

$RepoRoot    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ProjectPath = Join-Path $RepoRoot 'order-intake-bc'
$PackagePath = Join-Path $ProjectPath '.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.10.app'
$AppJsonPath = Join-Path $ProjectPath 'app.json'

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
    if ([string]::IsNullOrWhiteSpace($t)) { throw 'Could not acquire Business Central access token.' }
    return $t
}

function Assert-BcUri {
    param([Parameter(Mandatory)][string]$Uri)
    $u = [Uri]$Uri
    if ($u.Scheme -ne 'https' -or $u.Host -ne 'api.businesscentral.dynamics.com') {
        throw "Unexpected Business Central URI blocked: $Uri"
    }
    if ($Uri.IndexOf($ForbiddenEnv,[StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Forbidden legacy sandbox URI blocked: $Uri"
    }
    if ($Uri.IndexOf('/Production/',[StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Production-like URI blocked: $Uri"
    }
}

function Invoke-BcGet {
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers)
    Assert-BcUri $Uri
    Invoke-RestMethod -Method Get -Uri $Uri -Headers $Headers -TimeoutSec 120
}

function Invoke-BcGetAll {
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers,[int]$MaxPages=300)
    $rows = [System.Collections.Generic.List[object]]::new()
    $next = $Uri
    $page = 0
    while (-not [string]::IsNullOrWhiteSpace($next)) {
        $page++
        if ($page -gt $MaxPages) { throw "Pagination safety bound exceeded ($MaxPages pages): $Uri" }
        $response = Invoke-BcGet -Uri $next -Headers $Headers
        foreach ($row in @($response.value)) { $rows.Add($row) }
        $nextProp = $response.PSObject.Properties['@odata.nextLink']
        if ($null -eq $nextProp) { $next = $null } else { $next = [string]$nextProp.Value }
    }
    return @($rows)
}

function Invoke-BcJsonPost {
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers,[AllowNull()][object]$Body)
    Assert-BcUri $Uri
    if ($null -eq $Body) {
        return Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -ContentType 'application/json' -TimeoutSec 120
    }
    return Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -Body ($Body | ConvertTo-Json -Depth 20) -ContentType 'application/json' -TimeoutSec 120
}

function Escape-ODataLiteral {
    param([Parameter(Mandatory)][string]$Value)
    return $Value.Replace("'", "''")
}

function New-FilterUri {
    param([Parameter(Mandatory)][string]$EntitySet,[Parameter(Mandatory)][string]$Filter)
    $encoded = [Uri]::EscapeDataString($Filter)
    return "$customRoot/$EntitySet?`$filter=$encoded"
}

function Get-VersionString {
    param([Parameter(Mandatory)]$Extension)
    return ('{0}.{1}.{2}.{3}' -f $Extension.versionMajor,$Extension.versionMinor,$Extension.versionBuild,$Extension.versionRevision)
}

function Normalize-Reference {
    param([AllowNull()][string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $trimmed = $Value.Trim()
    if ($trimmed -match '^\d+$') {
        $n = $trimmed.TrimStart('0')
        if ([string]::IsNullOrWhiteSpace($n)) { return '0' }
        return $n
    }
    return ([regex]::Replace($trimmed.ToUpperInvariant(),'[^A-Z0-9]',''))
}

function Write-HeaderArchiveRow {
    param([Parameter(Mandatory)][string]$Label,[Parameter(Mandatory)]$Row)
    Write-Host ("HEADER_ARCHIVE|label={0}|order={1}|occurrence={2}|version={3}|customer={4}|external={5}|yourRef={6}|orderDate={7}|shipmentDate={8}|requested={9}|shipTo={10}|shipName={11}|shipAddr1={12}|shipCity={13}|shipPostal={14}|location={15}|archived={16} {17}" -f
        $Label,$Row.documentNumber,$Row.documentNumberOccurrence,$Row.versionNumber,$Row.sellToCustomerNumber,$Row.externalDocumentNumber,$Row.yourReference,$Row.orderDate,$Row.shipmentDate,$Row.requestedDeliveryDate,$Row.shipToCode,$Row.shipToName,$Row.shipToAddressLine1,$Row.shipToCity,$Row.shipToPostalCode,$Row.locationCode,$Row.dateArchived,$Row.timeArchived)
}

function Write-LineArchiveRow {
    param([Parameter(Mandatory)][string]$Label,[Parameter(Mandatory)]$Row)
    Write-Host ("LINE_ARCHIVE|label={0}|order={1}|occurrence={2}|version={3}|line={4}|customer={5}|item={6}|qty={7}|uom={8}|price={9}|amount={10}|location={11}|requested={12}|itemRef={13}|itemRefUom={14}|itemRefType={15}|itemRefTypeNo={16}" -f
        $Label,$Row.documentNumber,$Row.documentNumberOccurrence,$Row.versionNumber,$Row.lineNumber,$Row.sellToCustomerNumber,$Row.itemNumber,$Row.quantity,$Row.unitOfMeasureCode,$Row.unitPrice,$Row.lineAmount,$Row.locationCode,$Row.requestedDeliveryDate,$Row.itemReferenceNumber,$Row.itemReferenceUnitOfMeasure,$Row.itemReferenceType,$Row.itemReferenceTypeNumber)
}

function Write-InvoiceLineRow {
    param([Parameter(Mandatory)][string]$Label,[Parameter(Mandatory)]$Row)
    Write-Host ("INVOICE_LINE|label={0}|invoice={1}|line={2}|customer={3}|item={4}|description={5}|shipDate={6}|qty={7}|uom={8}|price={9}|location={10}|itemRef={11}|itemRefUom={12}|itemRefType={13}|itemRefTypeNo={14}|created={15}" -f
        $Label,$Row.documentNumber,$Row.lineNumber,$Row.sellToCustomerNumber,$Row.itemNumber,$Row.description,$Row.shipmentDate,$Row.quantity,$Row.unitOfMeasureCode,$Row.unitPrice,$Row.locationCode,$Row.itemReferenceNumber,$Row.itemReferenceUnitOfMeasure,$Row.itemReferenceType,$Row.itemReferenceTypeNumber,$Row.systemCreatedAt)
}

function Write-InvoiceHeaderRow {
    param([Parameter(Mandatory)][string]$Label,[Parameter(Mandatory)]$Row)
    Write-Host ("INVOICE_HEADER|label={0}|invoice={1}|customer={2}|order={3}|external={4}|yourRef={5}|orderDate={6}|postingDate={7}|shipmentDate={8}|shipTo={9}|shipName={10}|shipAddr1={11}|shipCity={12}|shipPostal={13}|location={14}|created={15}" -f
        $Label,$Row.documentNumber,$Row.sellToCustomerNumber,$Row.orderNumber,$Row.externalDocumentNumber,$Row.yourReference,$Row.orderDate,$Row.postingDate,$Row.shipmentDate,$Row.shipToCode,$Row.shipToName,$Row.shipToAddressLine1,$Row.shipToCity,$Row.shipToPostalCode,$Row.locationCode,$Row.systemCreatedAt)
}

# ---------------------------------------------------------------------------------------------------------------------
# Fail-closed local preflight.
# ---------------------------------------------------------------------------------------------------------------------
if (-not $EnableInstall) { throw 'REFUSING INSTALL: rerun with -EnableInstall for this exact PRE-only diagnostics upgrade.' }
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }
if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw "Compiled package not found: $PackagePath" }
if (-not (Test-Path -LiteralPath $AppJsonPath -PathType Leaf)) { throw "app.json not found: $AppJsonPath" }

$app = Get-Content -LiteralPath $AppJsonPath -Raw | ConvertFrom-Json
if ([string]$app.id -ne $ExpectedAppId -or [string]$app.name -ne $ExpectedAppName -or [string]$app.publisher -ne $ExpectedPublisher -or [string]$app.version -ne $ExpectedAppVersion) {
    throw 'Local app identity/version gate failed.'
}
$actualHash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash
if ($actualHash -ne $ExpectedPackageHash) { throw "Package SHA mismatch. Expected $ExpectedPackageHash; got $actualHash." }

$readOnlySources = @(
    'src\Page71208.GPIOrderIntakeSalesInvoiceLineHistoryAPI.al',
    'src\Page71211.GPIOrderIntakeSalesHeaderArchiveAPI.al',
    'src\Page71212.GPIOrderIntakeSalesLineArchiveAPI.al',
    'src\Page71213.GPIOrderIntakeSalesInvoiceHeaderAPI.al'
)
foreach ($relative in $readOnlySources) {
    $path = Join-Path $ProjectPath $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required diagnostics source missing: $path" }
    $text = Get-Content -LiteralPath $path -Raw
    foreach ($marker in @('InsertAllowed = false;','ModifyAllowed = false;','DeleteAllowed = false;')) {
        if ($text.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) { throw "Read-only API marker missing from ${path}: $marker" }
    }
}

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

# ---------------------------------------------------------------------------------------------------------------------
# Exact server target verification before extension mutation.
# ---------------------------------------------------------------------------------------------------------------------
$envs = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $headers
$envMatch = @($envs.value | Where-Object { [string]$_.name -eq $Environment })
if ($envMatch.Count -ne 1) { throw "Expected exactly one $Environment environment; found $($envMatch.Count)." }
$environmentType = [string]$envMatch[0].type
if ($environmentType -ine 'sandbox') { throw "SAFETY STOP: $Environment is type '$environmentType', not sandbox." }

$envEncoded = [Uri]::EscapeDataString($Environment)
$standardRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/v2.0"
$companies = Invoke-BcGet -Uri "$standardRoot/companies" -Headers $headers
$companyMatch = @($companies.value | Where-Object {
    [string]$_.id -eq $CompanyId -and (([string]$_.name -eq $CompanyName) -or ([string]$_.displayName -eq $CompanyName))
})
if ($companyMatch.Count -ne 1) { throw "Exact Gamer Packaging company verification failed; found $($companyMatch.Count)." }

$automationRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/microsoft/automation/v2.0/companies($CompanyId)"
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE 0.1.0.10 - HISTORICAL IDENTITY DIAGNOSTICS PUBLISH + GET-ONLY DISCOVERY / PRE ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment          : $Environment"
Write-Host "Environment type     : $environmentType"
Write-Host "Company              : $CompanyName"
Write-Host "Company ID           : $CompanyId"
Write-Host "Target app           : $ExpectedAppName $ExpectedAppVersion"
Write-Host "Package SHA256       : $actualHash"
Write-Host 'New diagnostics      : Sales Header Archive + Sales Line Archive + posted invoice header/item-reference fields / READ ONLY'
Write-Host 'Resolver behavior    : UNCHANGED from 0.1.0.8'
Write-Host 'Extension mutation   : EXACT 0.1.0.10 PRE upgrade only' -ForegroundColor Yellow
Write-Host 'Business-data writes : NONE' -ForegroundColor Green
Write-Host 'Sales-order action   : NOT CALLED / NOT PRESENT IN THIS HARNESS' -ForegroundColor Green
Write-Host 'Release/Ship/Post    : NOT CALLED / BLOCKED' -ForegroundColor Green
Write-Host 'Production           : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

# ---------------------------------------------------------------------------------------------------------------------
# Install exact 0.1.0.10 only if not already installed.
# ---------------------------------------------------------------------------------------------------------------------
$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$nameMatches = @($extensions.value | Where-Object { [string]$_.displayName -eq $ExpectedAppName -and [string]$_.publisher -eq $ExpectedPublisher })
$wrongId = @($nameMatches | Where-Object { [string]$_.id -ne $ExpectedAppId })
if ($wrongId.Count -gt 0) { throw 'A GPI Order Intake extension with an unexpected App ID exists. Stopping.' }

$exactInstalled = @($nameMatches | Where-Object { [string]$_.id -eq $ExpectedAppId -and (Get-VersionString $_) -eq $ExpectedAppVersion -and $_.isInstalled -eq $true })
if ($exactInstalled.Count -gt 1) { throw "More than one installed $ExpectedAppName $ExpectedAppVersion row was returned." }
$installedOther = @($nameMatches | Where-Object { [string]$_.id -eq $ExpectedAppId -and $_.isInstalled -eq $true -and (Get-VersionString $_) -ne $ExpectedAppVersion })
foreach ($row in $installedOther) {
    $v = Get-VersionString $row
    Write-Host "Currently installed prior version: $v"
    if ($v -notin @('0.1.0.9')) { throw "Unexpected installed prior version $v. Expected only 0.1.0.9 before this upgrade." }
}

if ($exactInstalled.Count -eq 1) {
    Write-Host "$ExpectedAppName $ExpectedAppVersion is already installed in PRE; skipping duplicate upload." -ForegroundColor Green
}
else {
    Write-Host 'Creating PRE extension-upload record...' -ForegroundColor Yellow
    $uploadRecord = Invoke-BcJsonPost -Uri "$automationRoot/extensionUpload" -Headers $headers -Body ([ordered]@{ schedule='Current version'; schemaSyncMode='Add' })
    $uploadId = [string]$uploadRecord.systemId
    if ([string]::IsNullOrWhiteSpace($uploadId)) { throw 'extensionUpload did not return systemId.' }

    Write-Host "Uploading certified 0.1.0.10 package to PRE upload record $uploadId..." -ForegroundColor Yellow
    $contentUri = "$automationRoot/extensionUpload($uploadId)/extensionContent"
    Assert-BcUri $contentUri
    $binaryHeaders = @{ Authorization = "Bearer $token"; Accept='application/json'; 'If-Match'='*' }
    $patch = Invoke-WebRequest -Method Patch -Uri $contentUri -Headers $binaryHeaders -ContentType 'application/octet-stream' -InFile $PackagePath -SkipHttpErrorCheck -TimeoutSec 180
    if ([int]$patch.StatusCode -lt 200 -or [int]$patch.StatusCode -ge 300) { throw "Extension content upload failed: HTTP $($patch.StatusCode) $($patch.Content)" }

    $deploymentStart = [DateTimeOffset]::UtcNow.AddSeconds(-15)
    Write-Host 'Starting PRE extension deployment...' -ForegroundColor Yellow
    $null = Invoke-BcJsonPost -Uri "$automationRoot/extensionUpload($uploadId)/Microsoft.NAV.upload" -Headers $headers -Body $null

    $completed = $false
    for ($attempt = 1; $attempt -le 90; $attempt++) {
        Start-Sleep -Seconds 2
        $statuses = Invoke-BcGet -Uri "$automationRoot/extensionDeploymentStatus?`$top=200" -Headers $headers
        $matches = @($statuses.value | Where-Object {
            [string]$_.name -eq $ExpectedAppName -and [string]$_.publisher -eq $ExpectedPublisher -and [string]$_.appVersion -eq $ExpectedAppVersion -and ([DateTimeOffset]$_.startedOn) -ge $deploymentStart
        } | Sort-Object { [DateTimeOffset]$_.startedOn } -Descending)
        if ($matches.Count -eq 0) { continue }
        $latest = $matches[0]
        Write-Host "Deployment status: $($latest.status)" -ForegroundColor Yellow
        if ([string]$latest.status -match '(?i)fail|error|cancel') { throw "GPI Order Intake deployment failed with status '$($latest.status)'." }
        if ([string]$latest.status -match '(?i)complete|success') { $completed = $true; break }
    }
    if (-not $completed) { throw 'Timed out waiting for GPI Order Intake deployment to complete.' }
}

$extensionsAfter = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$installed = @($extensionsAfter.value | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and [string]$_.displayName -eq $ExpectedAppName -and [string]$_.publisher -eq $ExpectedPublisher -and (Get-VersionString $_) -eq $ExpectedAppVersion -and $_.isInstalled -eq $true
})
if ($installed.Count -ne 1) { throw "Post-deployment verification expected one installed $ExpectedAppName $ExpectedAppVersion; found $($installed.Count)." }
Write-Host 'PRE 0.1.0.10 extension install verification: PASS' -ForegroundColor Green

# Wait for all historical diagnostic APIs to become available.
$apiChecks = @(
    "$customRoot/orderIntakeSalesHeaderArchives?`$top=1",
    "$customRoot/orderIntakeSalesLineArchives?`$top=1",
    "$customRoot/orderIntakeSalesInvoiceHeaderHistories?`$top=1",
    "$customRoot/orderIntakeSalesInvoiceLineHistories?`$top=1"
)
foreach ($uri in $apiChecks) {
    $ready = $false
    for ($attempt = 1; $attempt -le 45; $attempt++) {
        try { $null = Invoke-BcGet -Uri $uri -Headers $headers; $ready = $true; break }
        catch { Start-Sleep -Seconds 2 }
    }
    if (-not $ready) { throw "Historical diagnostics API did not become available: $uri" }
}
Write-Host 'Read-only historical diagnostics API availability: PASS' -ForegroundColor Green

# ---------------------------------------------------------------------------------------------------------------------
# Berner: exact historical Sales Order archive proof.
# ---------------------------------------------------------------------------------------------------------------------
Write-Host ''
Write-Host 'BERNER_HISTORICAL_SALES_ORDER_IDENTITY' -ForegroundColor Cyan
$bernerHeaderFilter = "documentNumber eq '$(Escape-ODataLiteral $BernerOrder)'"
$bernerHeaders = @(Invoke-BcGetAll -Uri (New-FilterUri 'orderIntakeSalesHeaderArchives' $bernerHeaderFilter) -Headers $headers)
$bernerHeaders = @($bernerHeaders | Where-Object { [string]$_.sellToCustomerNumber -eq $BernerCustomer })
Write-Host "BERNER_HEADER_ARCHIVE_TOTAL=$($bernerHeaders.Count)"
foreach ($row in @($bernerHeaders | Sort-Object {[int]$_.versionNumber}, {[int]$_.documentNumberOccurrence})) { Write-HeaderArchiveRow -Label 'BERNER' -Row $row }

$bernerLineFilter = "documentNumber eq '$(Escape-ODataLiteral $BernerOrder)' and itemNumber eq '$(Escape-ODataLiteral $BernerItem)'"
$bernerLines = @(Invoke-BcGetAll -Uri (New-FilterUri 'orderIntakeSalesLineArchives' $bernerLineFilter) -Headers $headers)
$bernerLines = @($bernerLines | Where-Object { [string]$_.sellToCustomerNumber -eq $BernerCustomer })
Write-Host "BERNER_LINE_ARCHIVE_TOTAL=$($bernerLines.Count)"
foreach ($row in @($bernerLines | Sort-Object {[int]$_.versionNumber}, {[int]$_.lineNumber})) { Write-LineArchiveRow -Label 'BERNER' -Row $row }

$bernerRefNorm = Normalize-Reference $BernerSourceRef
$bernerRefMatches = @($bernerLines | Where-Object { (Normalize-Reference ([string]$_.itemReferenceNumber)) -eq $bernerRefNorm })
$bernerPoMatches = @($bernerHeaders | Where-Object { (Normalize-Reference ([string]$_.externalDocumentNumber)) -eq (Normalize-Reference $BernerSourcePo) -or (Normalize-Reference ([string]$_.yourReference)) -eq (Normalize-Reference $BernerSourcePo) })
$bernerShipMatches = @($bernerHeaders | Where-Object { [string]$_.shipToCode -eq $BernerShipToCode })
Write-Host ("BERNER_HISTORICAL_IDENTITY_SUMMARY|order={0}|sourcePo={1}|sourceRef={2}|item={3}|headerRows={4}|poHeaderMatches={5}|shipToCode={6}|shipToHeaderMatches={7}|lineRows={8}|itemRefMatches={9}" -f
    $BernerOrder,$BernerSourcePo,$BernerSourceRef,$BernerItem,$bernerHeaders.Count,$bernerPoMatches.Count,$BernerShipToCode,$bernerShipMatches.Count,$bernerLines.Count,$bernerRefMatches.Count)

# ---------------------------------------------------------------------------------------------------------------------
# Herdez: posted invoice-line reference evidence joined to invoice headers.
# ---------------------------------------------------------------------------------------------------------------------
Write-Host ''
Write-Host 'HERDEZ_POSTED_TRANSACTION_IDENTITY' -ForegroundColor Cyan
$herdezLineFilter = "sellToCustomerNumber eq '$(Escape-ODataLiteral $HerdezCustomer)' and itemNumber eq '$(Escape-ODataLiteral $HerdezItem)'"
$herdezLines = @(Invoke-BcGetAll -Uri (New-FilterUri 'orderIntakeSalesInvoiceLineHistories' $herdezLineFilter) -Headers $headers)
$herdezLines = @($herdezLines | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
Write-Host "HERDEZ_INVOICE_LINE_TOTAL=$($herdezLines.Count)"
foreach ($row in $herdezLines) { Write-InvoiceLineRow -Label 'HERDEZ' -Row $row }

$invoiceNumbers = @($herdezLines | ForEach-Object { [string]$_.documentNumber } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique)
$herdezHeaders = [System.Collections.Generic.List[object]]::new()
foreach ($invoiceNo in $invoiceNumbers) {
    $filter = "documentNumber eq '$(Escape-ODataLiteral $invoiceNo)'"
    foreach ($row in @(Invoke-BcGetAll -Uri (New-FilterUri 'orderIntakeSalesInvoiceHeaderHistories' $filter) -Headers $headers)) { $herdezHeaders.Add($row) }
}
$herdezHeadersArray = @($herdezHeaders | Where-Object { [string]$_.sellToCustomerNumber -eq $HerdezCustomer } | Sort-Object {[DateTimeOffset]$_.systemCreatedAt} -Descending)
Write-Host "HERDEZ_INVOICE_HEADER_TOTAL=$($herdezHeadersArray.Count)"
foreach ($row in $herdezHeadersArray) { Write-InvoiceHeaderRow -Label 'HERDEZ' -Row $row }

$herdezRefNorm = Normalize-Reference $HerdezSourceRef
$herdezRefMatches = @($herdezLines | Where-Object { (Normalize-Reference ([string]$_.itemReferenceNumber)) -eq $herdezRefNorm })
$herdezPoMatches = @($herdezHeadersArray | Where-Object { (Normalize-Reference ([string]$_.externalDocumentNumber)) -eq (Normalize-Reference $HerdezSourcePo) -or (Normalize-Reference ([string]$_.yourReference)) -eq (Normalize-Reference $HerdezSourcePo) })
$herdezShipMatches = @($herdezHeadersArray | Where-Object { [string]$_.shipToCode -eq $HerdezShipToCode })
Write-Host ("HERDEZ_HISTORICAL_IDENTITY_SUMMARY|sourcePo={0}|sourceRef={1}|item={2}|invoiceLines={3}|itemRefMatches={4}|invoiceHeaders={5}|poHeaderMatches={6}|shipToCode={7}|shipToHeaderMatches={8}" -f
    $HerdezSourcePo,$HerdezSourceRef,$HerdezItem,$herdezLines.Count,$herdezRefMatches.Count,$herdezHeadersArray.Count,$herdezPoMatches.Count,$HerdezShipToCode,$herdezShipMatches.Count)

$result = [ordered]@{
    success = $true
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    installedApp = "$ExpectedAppName $ExpectedAppVersion"
    packageSha256 = $actualHash
    berner = [ordered]@{
        salesOrder = $BernerOrder
        sourcePo = $BernerSourcePo
        sourceReference = $BernerSourceRef
        expectedItem = $BernerItem
        expectedShipTo = $BernerShipToCode
        headerArchiveRows = $bernerHeaders.Count
        sourcePoHeaderMatches = $bernerPoMatches.Count
        shipToHeaderMatches = $bernerShipMatches.Count
        lineArchiveRows = $bernerLines.Count
        sourceReferenceLineMatches = $bernerRefMatches.Count
    }
    herdez = [ordered]@{
        sourcePo = $HerdezSourcePo
        sourceReference = $HerdezSourceRef
        expectedItem = $HerdezItem
        expectedShipTo = $HerdezShipToCode
        invoiceLineRows = $herdezLines.Count
        sourceReferenceLineMatches = $herdezRefMatches.Count
        invoiceHeaderRows = $herdezHeadersArray.Count
        sourcePoHeaderMatches = $herdezPoMatches.Count
        shipToHeaderMatches = $herdezShipMatches.Count
    }
    writeAuthorization = 'NOT_GRANTED'
    safety = [ordered]@{
        extensionMutation = 'EXACT_0.1.0.10_PRE_UPGRADE_ONLY'
        businessDataReads = 'GET_ONLY_AFTER_INSTALL'
        businessDataWrites = 'NONE'
        salesOrderAction = 'NOT_CALLED'
        releaseShipInvoicePost = 'NOT_CALLED_BLOCKED'
        production = 'HARD_BLOCKED'
    }
}

Write-Host ''
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE 0.1.0.10 HISTORICAL IDENTITY DIAGNOSTICS RESULT' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'Extension install       : PASS / exact PRE 0.1.0.10'
Write-Host 'Historical archive reads: PASS / GET ONLY'
Write-Host 'Posted invoice reads    : PASS / GET ONLY'
Write-Host 'Business-data writes    : NONE'
Write-Host 'Sales-order action      : NOT CALLED'
Write-Host 'Write authorization     : NOT GRANTED'
Write-Host 'Production              : HARD BLOCKED'
Write-Host ('=' * 120) -ForegroundColor Cyan
$result | ConvertTo-Json -Depth 10
