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
$ExpectedAppVersion  = '0.1.0.9'
$ExpectedPackageHash = '8092784D61A9FF5E930B8D4034C7FACF99BA7087CC75EB348FF5E59968C9894F'

$Targets = @(
    [pscustomobject][ordered]@{
        Label='BERNER'; CustomerNumber='BERNER'; SourceReference='811476'; ExpectedItem='21759-858231';
        SourceShipToName='Berner Foods'; SourceShipToAddress='5778 Baxter Road'; SourceShipToCity='Rockford'; SourceShipToPostal='61109'
    },
    [pscustomobject][ordered]@{
        Label='HERDEZ'; CustomerNumber='HERDEZ'; SourceReference='000000000004003467'; ExpectedItem='20113526';
        SourceShipToName='SLP INDUSTRIES PLANT'; SourceShipToAddress='AV. INDUSTRIAS 3815'; SourceShipToCity='SLP'; SourceShipToPostal='78395'
    }
)

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ProjectPath = Join-Path $RepoRoot 'order-intake-bc'
$PackagePath = Join-Path $ProjectPath '.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.9.app'
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
        $result = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
        $token = Convert-TokenToString $result.Token
        if (-not [string]::IsNullOrWhiteSpace($token)) { return $token }
    }
    catch {}

    Write-Host 'Starting Business Central scoped Microsoft sign-in...' -ForegroundColor Yellow
    Disconnect-AzAccount -Scope Process -ErrorAction SilentlyContinue | Out-Null
    Connect-AzAccount -Tenant $TenantId -AuthScope 'https://api.businesscentral.dynamics.com' -Scope Process -ErrorAction Stop | Out-Null
    $result = Get-AzAccessToken -TenantId $TenantId -ResourceUrl 'https://api.businesscentral.dynamics.com' -ErrorAction Stop
    $token = Convert-TokenToString $result.Token
    if ([string]::IsNullOrWhiteSpace($token)) { throw 'Could not acquire Business Central access token.' }
    return $token
}

function Assert-BcUri {
    param([Parameter(Mandatory)][string]$Uri)
    $parsed = [Uri]$Uri
    if ($parsed.Scheme -ne 'https' -or $parsed.Host -ne 'api.businesscentral.dynamics.com') {
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
    param([Parameter(Mandatory)][string]$Uri,[Parameter(Mandatory)][hashtable]$Headers,[int]$MaxPages=200)
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

function Get-VersionString {
    param([Parameter(Mandatory)]$Extension)
    return ('{0}.{1}.{2}.{3}' -f $Extension.versionMajor,$Extension.versionMinor,$Extension.versionBuild,$Extension.versionRevision)
}

function Normalize-Reference {
    param([AllowNull()][string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return '' }
    $trimmed = $Value.Trim()
    if ($trimmed -match '^\d+$') {
        $withoutZeros = $trimmed.TrimStart('0')
        if ([string]::IsNullOrEmpty($withoutZeros)) { return '0' }
        return $withoutZeros
    }
    return ([regex]::Replace($trimmed.ToUpperInvariant(),'[^A-Z0-9]',''))
}

function Test-TextContains {
    param([AllowNull()][string]$Text,[AllowNull()][string]$Needle)
    if ([string]::IsNullOrWhiteSpace($Text) -or [string]::IsNullOrWhiteSpace($Needle)) { return $false }
    return $Text.IndexOf($Needle,[StringComparison]::OrdinalIgnoreCase) -ge 0
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

$appJson = Get-Content -LiteralPath $AppJsonPath -Raw | ConvertFrom-Json
if ([string]$appJson.id -ne $ExpectedAppId -or [string]$appJson.name -ne $ExpectedAppName -or [string]$appJson.publisher -ne $ExpectedPublisher -or [string]$appJson.version -ne $ExpectedAppVersion) {
    throw 'Local app identity/version gate failed.'
}

$actualHash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash
if ($actualHash -ne $ExpectedPackageHash) {
    throw "Package SHA mismatch. Expected $ExpectedPackageHash; got $actualHash."
}

$source71209 = Join-Path $ProjectPath 'src\Page71209.GPIOrderIntakeItemReferenceAPI.al'
$source71210 = Join-Path $ProjectPath 'src\Page71210.GPIOrderIntakeShipToAPI.al'
foreach ($requiredPath in @($source71209,$source71210)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw "Required diagnostics source missing: $requiredPath" }
    $text = Get-Content -LiteralPath $requiredPath -Raw
    foreach ($marker in @('InsertAllowed = false;','ModifyAllowed = false;','DeleteAllowed = false;')) {
        if ($text.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) { throw "Read-only API marker missing from $requiredPath: $marker" }
    }
}

$token = Get-BcToken
$headers = @{ Authorization = "Bearer $token"; Accept = 'application/json' }

# ---------------------------------------------------------------------------------------------------------------------
# Server-side exact target verification before extension mutation.
# ---------------------------------------------------------------------------------------------------------------------
$environments = Invoke-BcGet -Uri 'https://api.businesscentral.dynamics.com/environments/v1.2' -Headers $headers
$envMatches = @($environments.value | Where-Object { [string]$_.name -eq $Environment })
if ($envMatches.Count -ne 1) { throw "Expected exactly one $Environment environment; found $($envMatches.Count)." }
$environmentType = [string]$envMatches[0].type
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
Write-Host 'GPI ORDER INTAKE 0.1.0.9 - IDENTITY DIAGNOSTICS PUBLISH + GET-ONLY DISCOVERY / PRE ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Environment          : $Environment"
Write-Host "Environment type     : $environmentType"
Write-Host "Company              : $CompanyName"
Write-Host "Company ID           : $CompanyId"
Write-Host "Target app           : $ExpectedAppName $ExpectedAppVersion"
Write-Host "Package SHA256       : $actualHash"
Write-Host 'New diagnostics      : Item Reference + Ship-to Address / READ ONLY'
Write-Host 'Resolver behavior    : UNCHANGED from 0.1.0.8'
Write-Host 'Extension mutation   : EXACT 0.1.0.9 PRE upgrade only' -ForegroundColor Yellow
Write-Host 'Business-data writes : NONE' -ForegroundColor Green
Write-Host 'Sales-order action   : NOT CALLED / NOT PRESENT IN THIS HARNESS' -ForegroundColor Green
Write-Host 'Release/Ship/Post    : NOT CALLED / BLOCKED' -ForegroundColor Green
Write-Host 'Production           : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

$extensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$nameMatches = @($extensions.value | Where-Object {
    [string]$_.displayName -eq $ExpectedAppName -and [string]$_.publisher -eq $ExpectedPublisher
})
$wrongId = @($nameMatches | Where-Object { [string]$_.id -ne $ExpectedAppId })
if ($wrongId.Count -gt 0) { throw 'A GPI Order Intake extension with an unexpected App ID exists. Stopping.' }

$exactInstalled = @($nameMatches | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and (Get-VersionString $_) -eq $ExpectedAppVersion -and $_.isInstalled -eq $true
})
if ($exactInstalled.Count -gt 1) { throw "More than one installed $ExpectedAppName $ExpectedAppVersion row was returned." }

$installedOther = @($nameMatches | Where-Object { [string]$_.id -eq $ExpectedAppId -and $_.isInstalled -eq $true -and (Get-VersionString $_) -ne $ExpectedAppVersion })
foreach ($row in $installedOther) {
    $v = Get-VersionString $row
    Write-Host "Currently installed prior version: $v"
    if ($v -notin @('0.1.0.8')) { throw "Unexpected installed prior version $v. Expected only 0.1.0.8 before this upgrade." }
}

if ($exactInstalled.Count -eq 1) {
    Write-Host "$ExpectedAppName $ExpectedAppVersion is already installed in PRE; skipping duplicate upload." -ForegroundColor Green
}
else {
    Write-Host 'Creating PRE extension-upload record...' -ForegroundColor Yellow
    $uploadRecord = Invoke-BcJsonPost -Uri "$automationRoot/extensionUpload" -Headers $headers -Body ([ordered]@{
        schedule = 'Current version'
        schemaSyncMode = 'Add'
    })
    $uploadId = [string]$uploadRecord.systemId
    if ([string]::IsNullOrWhiteSpace($uploadId)) { throw 'extensionUpload did not return systemId.' }

    Write-Host "Uploading certified 0.1.0.9 package to PRE upload record $uploadId..." -ForegroundColor Yellow
    $contentUri = "$automationRoot/extensionUpload($uploadId)/extensionContent"
    Assert-BcUri $contentUri
    $binaryHeaders = @{ Authorization = "Bearer $token"; Accept = 'application/json'; 'If-Match' = '*' }
    $patchResult = Invoke-WebRequest -Method Patch -Uri $contentUri -Headers $binaryHeaders -ContentType 'application/octet-stream' -InFile $PackagePath -SkipHttpErrorCheck -TimeoutSec 180
    if ([int]$patchResult.StatusCode -lt 200 -or [int]$patchResult.StatusCode -ge 300) {
        throw "Extension content upload failed: HTTP $($patchResult.StatusCode) $($patchResult.Content)"
    }

    $deploymentStart = [DateTimeOffset]::UtcNow.AddSeconds(-15)
    Write-Host 'Starting PRE extension deployment...' -ForegroundColor Yellow
    $null = Invoke-BcJsonPost -Uri "$automationRoot/extensionUpload($uploadId)/Microsoft.NAV.upload" -Headers $headers -Body $null

    $completed = $false
    for ($attempt = 1; $attempt -le 90; $attempt++) {
        Start-Sleep -Seconds 2
        $statuses = Invoke-BcGet -Uri "$automationRoot/extensionDeploymentStatus?`$top=200" -Headers $headers
        $statusMatches = @($statuses.value | Where-Object {
            [string]$_.name -eq $ExpectedAppName -and
            [string]$_.publisher -eq $ExpectedPublisher -and
            [string]$_.appVersion -eq $ExpectedAppVersion -and
            ([DateTimeOffset]$_.startedOn) -ge $deploymentStart
        } | Sort-Object { [DateTimeOffset]$_.startedOn } -Descending)

        if ($statusMatches.Count -eq 0) { continue }
        $latest = $statusMatches[0]
        Write-Host "Deployment status: $($latest.status)" -ForegroundColor Yellow
        if ([string]$latest.status -match '(?i)fail|error|cancel') {
            throw "GPI Order Intake deployment failed with status '$($latest.status)'."
        }
        if ([string]$latest.status -match '(?i)complete|success') {
            $completed = $true
            break
        }
    }
    if (-not $completed) { throw 'Timed out waiting for GPI Order Intake 0.1.0.9 deployment to complete.' }
}

$extensionsAfter = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $headers
$installed = @($extensionsAfter.value | Where-Object {
    [string]$_.id -eq $ExpectedAppId -and
    [string]$_.displayName -eq $ExpectedAppName -and
    [string]$_.publisher -eq $ExpectedPublisher -and
    (Get-VersionString $_) -eq $ExpectedAppVersion -and
    $_.isInstalled -eq $true
})
if ($installed.Count -ne 1) { throw "Post-deployment verification expected one installed $ExpectedAppName $ExpectedAppVersion; found $($installed.Count)." }
Write-Host 'PRE 0.1.0.9 extension install verification: PASS' -ForegroundColor Green

# ---------------------------------------------------------------------------------------------------------------------
# Wait for the two new read-only APIs. No sales-order action URI exists in this harness.
# ---------------------------------------------------------------------------------------------------------------------
$itemRefProbeUri = "$customRoot/orderIntakeItemReferences?`$top=1"
$shipToProbeUri = "$customRoot/orderIntakeShipToAddresses?`$top=1"
$apisReady = $false
for ($attempt = 1; $attempt -le 45; $attempt++) {
    try {
        $null = Invoke-BcGet -Uri $itemRefProbeUri -Headers $headers
        $null = Invoke-BcGet -Uri $shipToProbeUri -Headers $headers
        $apisReady = $true
        break
    }
    catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $apisReady) { throw 'New 0.1.0.9 diagnostics APIs did not become available after deployment.' }
Write-Host 'Read-only diagnostics API availability: PASS' -ForegroundColor Green

Write-Host ''
Write-Host 'ITEM_REFERENCE_DISCOVERY' -ForegroundColor Cyan
$itemReferences = @(Invoke-BcGetAll -Uri "$customRoot/orderIntakeItemReferences?`$top=200" -Headers $headers)
Write-Host "ITEM_REFERENCE_TOTAL_ROWS=$($itemReferences.Count)"

$referenceSummaries = [System.Collections.Generic.List[object]]::new()
foreach ($target in $Targets) {
    $sourceNorm = Normalize-Reference $target.SourceReference
    $matches = @($itemReferences | Where-Object {
        $typeNo = [string]$_.referenceTypeNumber
        $refNo = [string]$_.referenceNumber
        $itemNo = [string]$_.itemNumber
        ($typeNo -eq $target.CustomerNumber -and $refNo -eq $target.SourceReference) -or
        ($typeNo -eq $target.CustomerNumber -and $itemNo -eq $target.ExpectedItem) -or
        ($refNo -eq $target.SourceReference)
    })

    $exactCustomerRef = @($matches | Where-Object {
        [string]$_.referenceTypeNumber -eq $target.CustomerNumber -and [string]$_.referenceNumber -eq $target.SourceReference
    })

    $normalizedCandidates = @($itemReferences | Where-Object {
        [string]$_.referenceTypeNumber -eq $target.CustomerNumber -and
        (Normalize-Reference ([string]$_.referenceNumber)) -eq $sourceNorm
    })

    Write-Host "ITEM_REF_TARGET|label=$($target.Label)|customer=$($target.CustomerNumber)|sourceRef=$($target.SourceReference)|expectedItem=$($target.ExpectedItem)|exactCustomerRefMatches=$($exactCustomerRef.Count)|normalizedCustomerRefMatches=$($normalizedCandidates.Count)"

    foreach ($row in $matches) {
        Write-Host ('ITEM_REF_MATCH|label={0}|type={1}|typeNo={2}|reference={3}|item={4}|uom={5}|variant={6}|start={7}|end={8}|description={9}' -f $target.Label,$row.referenceType,$row.referenceTypeNumber,$row.referenceNumber,$row.itemNumber,$row.unitOfMeasureCode,$row.variantCode,$row.startingDate,$row.endingDate,$row.description)
    }
    if ($matches.Count -eq 0) { Write-Host "ITEM_REF_MATCH|label=$($target.Label)|NONE" }

    foreach ($row in @($normalizedCandidates | Where-Object { $exactCustomerRef -notcontains $_ })) {
        Write-Host ('ITEM_REF_NORMALIZED_CANDIDATE|label={0}|type={1}|typeNo={2}|reference={3}|item={4}|uom={5}|start={6}|end={7}' -f $target.Label,$row.referenceType,$row.referenceTypeNumber,$row.referenceNumber,$row.itemNumber,$row.unitOfMeasureCode,$row.startingDate,$row.endingDate)
    }

    $resolvedExact = @($exactCustomerRef | Where-Object { [string]$_.itemNumber -eq $target.ExpectedItem })
    $referenceSummaries.Add([pscustomobject][ordered]@{
        label=$target.Label
        customerNumber=$target.CustomerNumber
        sourceReference=$target.SourceReference
        expectedItem=$target.ExpectedItem
        exactCustomerReferenceMatches=$exactCustomerRef.Count
        exactExpectedItemMatches=$resolvedExact.Count
        normalizedCustomerReferenceCandidates=$normalizedCandidates.Count
    })
}

Write-Host ''
Write-Host 'SHIP_TO_DISCOVERY' -ForegroundColor Cyan
$shipTos = @(Invoke-BcGetAll -Uri "$customRoot/orderIntakeShipToAddresses?`$top=200" -Headers $headers)
Write-Host "SHIP_TO_TOTAL_ROWS=$($shipTos.Count)"

$shipToSummaries = [System.Collections.Generic.List[object]]::new()
foreach ($target in $Targets) {
    $rows = @($shipTos | Where-Object { [string]$_.customerNumber -eq $target.CustomerNumber })
    Write-Host "SHIP_TO_TARGET|label=$($target.Label)|customer=$($target.CustomerNumber)|rows=$($rows.Count)|sourceName=$($target.SourceShipToName)|sourceAddress=$($target.SourceShipToAddress)|sourceCity=$($target.SourceShipToCity)|sourcePostal=$($target.SourceShipToPostal)"

    $strongCandidates = [System.Collections.Generic.List[object]]::new()
    foreach ($row in $rows) {
        $score = 0
        if ((Test-TextContains ([string]$row.name) $target.SourceShipToName) -or (Test-TextContains $target.SourceShipToName ([string]$row.name))) { $score++ }
        if ((Test-TextContains ([string]$row.addressLine1) $target.SourceShipToAddress) -or (Test-TextContains $target.SourceShipToAddress ([string]$row.addressLine1))) { $score++ }
        if ((Test-TextContains ([string]$row.city) $target.SourceShipToCity) -or (Test-TextContains $target.SourceShipToCity ([string]$row.city))) { $score++ }
        if (-not [string]::IsNullOrWhiteSpace($target.SourceShipToPostal) -and [string]$row.postalCode -eq $target.SourceShipToPostal) { $score++ }
        if ($score -ge 2) { $strongCandidates.Add($row) }
        Write-Host ('SHIP_TO_MATCH|label={0}|score={1}|code={2}|name={3}|address1={4}|address2={5}|city={6}|state={7}|postal={8}|country={9}|location={10}|shipmentMethod={11}' -f $target.Label,$score,$row.code,$row.name,$row.addressLine1,$row.addressLine2,$row.city,$row.state,$row.postalCode,$row.countryCode,$row.locationCode,$row.shipmentMethodCode)
    }
    if ($rows.Count -eq 0) { Write-Host "SHIP_TO_MATCH|label=$($target.Label)|NONE" }

    $shipToSummaries.Add([pscustomobject][ordered]@{
        label=$target.Label
        customerNumber=$target.CustomerNumber
        shipToRows=$rows.Count
        strongSourceCandidates=$strongCandidates.Count
    })
}

Write-Host ''
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE 0.1.0.9 IDENTITY DIAGNOSTICS RESULT' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'Extension install      : PASS / exact PRE 0.1.0.9'
Write-Host 'Item Reference reads   : PASS / GET ONLY'
Write-Host 'Ship-to Address reads  : PASS / GET ONLY'
Write-Host 'Business-data writes   : NONE'
Write-Host 'Sales-order action     : NOT CALLED'
Write-Host 'Write authorization    : NOT GRANTED by this diagnostics run'
Write-Host 'Production             : HARD BLOCKED'
Write-Host ('=' * 120) -ForegroundColor Cyan

[pscustomobject][ordered]@{
    success=$true
    environment=$Environment
    environmentType=$environmentType
    company=$CompanyName
    installedApp="$ExpectedAppName $ExpectedAppVersion"
    packageSha256=$actualHash
    itemReferenceSummary=@($referenceSummaries)
    shipToSummary=@($shipToSummaries)
    writeAuthorization='NOT_GRANTED'
    safety=[ordered]@{
        extensionMutation='EXACT_0.1.0.9_PRE_UPGRADE_ONLY'
        businessDataReads='GET_ONLY_AFTER_INSTALL'
        businessDataWrites='NONE'
        salesOrderAction='NOT_CALLED'
        releaseShipInvoicePost='NOT_CALLED_BLOCKED'
        production='HARD_BLOCKED'
    }
} | ConvertTo-Json -Depth 10
