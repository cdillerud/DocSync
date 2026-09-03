#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY DIAGNOSTICS TARGET
# =====================================================================================================================
$TenantId          = 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc'
$Environment       = 'PRE_GAMERDOCS_CUTOVER_20260831'
$CompanyName       = 'Gamer Packaging'
$CompanyId         = '7d84c6d5-81e2-eb11-86df-00224822baa7'
$ForbiddenEnv      = 'Sandbox_NoZetadocs_UAT'
$EnableFlag        = 'GPI_ORDER_INTAKE_PRICING_DIAGNOSTICS_ENABLED'

$ExpectedAppId       = 'fcb4d73a-731e-47a4-85fa-8a49033cd3da'
$ExpectedAppName     = 'GPI Order Intake'
$ExpectedPublisher   = 'Gamer Packaging Inc'
$ExpectedAppVersion  = '0.1.0.1'
$ExpectedPackageHash = '8CC6ED106EFC4FD66BF642DE69DB4D7956157EB8FD5CB322EDD15268369A41AB'

$CustomerNumber = 'GIOVANN'
$ItemNumber     = 'C-503003-12033922'
$Quantity       = [decimal]56.42
$UomCode        = 'M'
$LocationCode   = '00'
$EvidencePrice  = [decimal]277.99
$EvidenceDate   = [datetime]'2026-09-01'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PackagePath = Join-Path $RepoRoot 'order-intake-bc\.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.1.app'

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
    $Value.Replace("'", "''")
}

# ---------------------------------------------------------------------------------------------------------------------
# Fail-closed local preflight.
# ---------------------------------------------------------------------------------------------------------------------
if ($TenantId -ne 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc') { throw 'Tenant hard pin changed.' }
if ($Environment -ne 'PRE_GAMERDOCS_CUTOVER_20260831') { throw 'Environment hard pin changed.' }
if ($Environment -eq $ForbiddenEnv -or $Environment -match '(?i)prod|production') { throw 'Forbidden environment.' }
if ($CompanyName -ne 'Gamer Packaging' -or $CompanyId -ne '7d84c6d5-81e2-eb11-86df-00224822baa7') { throw 'Company hard pin changed.' }
if ([Environment]::GetEnvironmentVariable($EnableFlag) -ine 'true') {
    throw "REFUSING PRE DIAGNOSTICS DEPLOYMENT: set `$env:$EnableFlag = 'true' explicitly."
}
if (-not (Test-Path $PackagePath)) { throw "Compiled diagnostics package not found: $PackagePath" }
$actualHash = (Get-FileHash $PackagePath -Algorithm SHA256).Hash
if ($actualHash -ne $ExpectedPackageHash) {
    throw "Package SHA256 mismatch. Expected $ExpectedPackageHash; got $actualHash."
}

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

# Server-side verification before extension mutation.
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
$customRoot = "https://api.businesscentral.dynamics.com/v2.0/$TenantId/$envEncoded/api/gpi/orderIntake/v1.0/companies($CompanyId)"

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - PRE PRICING DIAGNOSTICS DEPLOY + GET-ONLY READ' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment       : $Environment"
Write-Host "Environment type  : $environmentType"
Write-Host "Company           : $CompanyName"
Write-Host "Company ID        : $CompanyId"
Write-Host "App               : $ExpectedAppName $ExpectedAppVersion"
Write-Host "App ID            : $ExpectedAppId"
Write-Host "Package SHA256    : $actualHash"
Write-Host "Diagnostic customer: $CustomerNumber"
Write-Host "Diagnostic item   : $ItemNumber"
Write-Host "Known evidence    : $Quantity $UomCode / location $LocationCode / historical price $EvidencePrice"
Write-Host 'Sales-order action: NOT CALLED' -ForegroundColor Green
Write-Host 'Business data writes: NONE' -ForegroundColor Green
Write-Host 'Release/Ship/Post : NOT IMPLEMENTED / BLOCKED' -ForegroundColor Green
Write-Host 'Production        : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

# ---------------------------------------------------------------------------------------------------------------------
# Upgrade/install the exact diagnostics version only if needed.
# ---------------------------------------------------------------------------------------------------------------------
$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=200" -Headers $headers
$appMatches = @($extensions.value | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and
    [string]$_.displayName -eq $ExpectedAppName -and
    [string]$_.publisher -eq $ExpectedPublisher
})

$exactInstalled = @($appMatches | Where-Object {
    [int]$_.versionMajor -eq 0 -and [int]$_.versionMinor -eq 1 -and [int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 1 -and
    $_.isInstalled -eq $true
})
if ($exactInstalled.Count -gt 1) { throw 'More than one exact GPI Order Intake 0.1.0.1 installation was returned.' }

$deploymentPerformed = $false
if ($exactInstalled.Count -eq 1) {
    Write-Host 'GPI Order Intake 0.1.0.1 is already installed in PRE; skipping duplicate deployment.' -ForegroundColor Green
}
else {
    $conflictingIds = @($extensions.value | Where-Object {
        [string]$_.displayName -eq $ExpectedAppName -and [string]$_.publisher -eq $ExpectedPublisher -and [string]$_.id -ne $ExpectedAppId
    })
    if ($conflictingIds.Count -gt 0) { throw 'A GPI Order Intake app with an unexpected App ID exists. Stopping.' }

    Write-Host 'Creating PRE diagnostics extension-upload record...' -ForegroundColor Yellow
    $uploadRecord = Invoke-BcPost -Uri "$automationRoot/extensionUpload" -Headers $headers -Body ([ordered]@{
        schedule = 'Current version'
        schemaSyncMode = 'Add'
    })
    $uploadId = [string]$uploadRecord.systemId
    if ([string]::IsNullOrWhiteSpace($uploadId)) { throw 'extensionUpload did not return systemId.' }

    $contentUri = "$automationRoot/extensionUpload($uploadId)/extensionContent"
    Assert-BcUri $contentUri
    $binaryHeaders = @{ Authorization = "Bearer $token"; Accept = 'application/json'; 'If-Match' = '*' }
    Write-Host "Uploading vetted diagnostics package to PRE upload record $uploadId..." -ForegroundColor Yellow
    $patch = Invoke-WebRequest -Method Patch -Uri $contentUri -Headers $binaryHeaders -ContentType 'application/octet-stream' -InFile $PackagePath -SkipHttpErrorCheck -TimeoutSec 180
    if ([int]$patch.StatusCode -lt 200 -or [int]$patch.StatusCode -ge 300) {
        throw "Extension content upload failed: HTTP $($patch.StatusCode) $($patch.Content)"
    }

    $deploymentStart = [DateTimeOffset]::UtcNow.AddSeconds(-15)
    Write-Host 'Starting PRE diagnostics extension deployment...' -ForegroundColor Yellow
    $null = Invoke-BcPost -Uri "$automationRoot/extensionUpload($uploadId)/Microsoft.NAV.upload" -Headers $headers

    $completed = $false
    for ($attempt = 1; $attempt -le 90; $attempt++) {
        Start-Sleep -Seconds 2
        $statuses = Invoke-BcGet -Uri "$automationRoot/extensionDeploymentStatus?`$top=200" -Headers $headers
        $matches = @($statuses.value | Where-Object {
            [string]$_.name -eq $ExpectedAppName -and
            [string]$_.publisher -eq $ExpectedPublisher -and
            [string]$_.appVersion -eq $ExpectedAppVersion -and
            ([DateTimeOffset]$_.startedOn) -ge $deploymentStart
        } | Sort-Object { [DateTimeOffset]$_.startedOn } -Descending)

        if ($matches.Count -eq 0) { continue }
        $latest = $matches[0]
        Write-Host "Deployment status: $($latest.status)" -ForegroundColor Yellow
        if ([string]$latest.status -match '(?i)fail|error|cancel') {
            throw "GPI Order Intake diagnostics deployment failed with status '$($latest.status)'."
        }
        if ([string]$latest.status -match '(?i)complete|success') {
            $completed = $true
            $deploymentPerformed = $true
            break
        }
    }
    if (-not $completed) { throw 'Timed out waiting for GPI Order Intake diagnostics deployment.' }
}

# Verify exact diagnostics version is installed.
$extensionsAfter = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=200" -Headers $headers
$installed = @($extensionsAfter.value | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and
    [string]$_.displayName -eq $ExpectedAppName -and
    [string]$_.publisher -eq $ExpectedPublisher -and
    [int]$_.versionMajor -eq 0 -and [int]$_.versionMinor -eq 1 -and [int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 1 -and
    $_.isInstalled -eq $true
})
if ($installed.Count -ne 1) { throw "Expected exactly one installed $ExpectedAppName $ExpectedAppVersion; found $($installed.Count)." }
Write-Host 'PRE diagnostics extension verification: PASS' -ForegroundColor Green

# ---------------------------------------------------------------------------------------------------------------------
# GET-only pricing diagnostics. No business-data mutation below this point.
# ---------------------------------------------------------------------------------------------------------------------
$customerLiteral = Escape-ODataLiteral $CustomerNumber
$customerFilter = [Uri]::EscapeDataString("number eq '$customerLiteral'")
$customerUri = "$customRoot/orderIntakeCustomers?`$filter=$customerFilter&`$top=2"

$customerResponse = $null
for ($attempt = 1; $attempt -le 45; $attempt++) {
    try {
        $customerResponse = Invoke-BcGet -Uri $customerUri -Headers $headers
        break
    }
    catch {
        Start-Sleep -Seconds 2
    }
}
if ($null -eq $customerResponse) { throw 'Order Intake diagnostics API did not become available after deployment.' }
$customers = @($customerResponse.value)
if ($customers.Count -ne 1) { throw "Expected exactly one diagnostics customer $CustomerNumber; found $($customers.Count)." }
$customer = $customers[0]

$itemLiteral = Escape-ODataLiteral $ItemNumber
$lineFilter = [Uri]::EscapeDataString("itemNumber eq '$itemLiteral'")
$openLinesResponse = Invoke-BcGet -Uri "$customRoot/orderIntakeLines?`$filter=$lineFilter&`$top=200" -Headers $headers
$openLines = @($openLinesResponse.value)

$priceFilter = [Uri]::EscapeDataString("assetNumber eq '$itemLiteral' or productNumber eq '$itemLiteral'")
$priceResponse = Invoke-BcGet -Uri "$customRoot/orderIntakePriceLines?`$filter=$priceFilter&`$top=500" -Headers $headers
$priceLines = @($priceResponse.value)

# Normalize customer source candidates as BC pricing context hints.
$sourceCandidates = @($CustomerNumber)
if (-not [string]::IsNullOrWhiteSpace([string]$customer.billToCustomerNumber)) { $sourceCandidates += [string]$customer.billToCustomerNumber }
if (-not [string]::IsNullOrWhiteSpace([string]$customer.customerPriceGroup)) { $sourceCandidates += [string]$customer.customerPriceGroup }
if (-not [string]::IsNullOrWhiteSpace([string]$customer.customerDiscountGroup)) { $sourceCandidates += [string]$customer.customerDiscountGroup }
$sourceCandidates = @($sourceCandidates | Sort-Object -Unique)

$relevantPriceLines = @($priceLines | Where-Object {
    $sourceNo = [string]$_.sourceNumber
    $parentSourceNo = [string]$_.parentSourceNumber
    $sourceMatch = ([string]::IsNullOrWhiteSpace($sourceNo) -or $sourceCandidates -contains $sourceNo -or $sourceCandidates -contains $parentSourceNo)

    $uomMatch = ([string]::IsNullOrWhiteSpace([string]$_.unitOfMeasureCode) -or [string]$_.unitOfMeasureCode -eq $UomCode)
    $qtyMatch = ([decimal]$_.minimumQuantity -le $Quantity)
    $currencyMatch = ([string]::IsNullOrWhiteSpace([string]$_.currencyCode) -or [string]$_.currencyCode -eq [string]$customer.currencyCode)

    $start = if ([string]::IsNullOrWhiteSpace([string]$_.startingDate) -or [string]$_.startingDate -eq '0001-01-01') { [datetime]::MinValue } else { [datetime]$_.startingDate }
    $end = if ([string]::IsNullOrWhiteSpace([string]$_.endingDate) -or [string]$_.endingDate -eq '0001-01-01') { [datetime]::MaxValue } else { [datetime]$_.endingDate }
    $dateMatch = ($EvidenceDate -ge $start -and $EvidenceDate -le $end)

    $sourceMatch -and $uomMatch -and $qtyMatch -and $currencyMatch -and $dateMatch
})

$price27799 = @($priceLines | Where-Object { [math]::Abs([double]([decimal]$_.unitPrice - $EvidencePrice)) -lt 0.005 })

$diagnostic = [ordered]@{
    success = $true
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    app = [ordered]@{
        id = $ExpectedAppId
        version = $ExpectedAppVersion
        packageSha256 = $actualHash
        deploymentPerformedThisRun = $deploymentPerformed
    }
    safety = [ordered]@{
        salesOrderActionCalled = $false
        businessDataWrites = 'NONE'
        releaseShipInvoicePost = 'NOT IMPLEMENTED / BLOCKED'
        production = 'HARD BLOCKED'
    }
    target = [ordered]@{
        customerNumber = $CustomerNumber
        itemNumber = $ItemNumber
        quantity = $Quantity
        unitOfMeasureCode = $UomCode
        locationCode = $LocationCode
        historicalEvidenceUnitPrice = $EvidencePrice
        evidenceDate = $EvidenceDate.ToString('yyyy-MM-dd')
    }
    customerPricingContext = $customer
    sourceCandidates = $sourceCandidates
    openSalesLineMatches = $openLines
    itemPriceListLines = $priceLines
    relevantPriceListLines = $relevantPriceLines
    exactHistoricalPriceMatches = $price27799
    counts = [ordered]@{
        openSalesLineMatches = $openLines.Count
        itemPriceListLines = $priceLines.Count
        relevantPriceListLines = $relevantPriceLines.Count
        exactHistoricalPriceMatches = $price27799.Count
    }
}

Write-Host ''
Write-Host ('=' * 120) -ForegroundColor Green
Write-Host 'GPI ORDER INTAKE PRE PRICING DIAGNOSTICS' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Green
$diagnostic | ConvertTo-Json -Depth 30
Write-Host ''
Write-Host 'Diagnostics completed with GET-only business-data access.' -ForegroundColor Green
Write-Host 'No Sales Order create/update/delete action was called.' -ForegroundColor Green
