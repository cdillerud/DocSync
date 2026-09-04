#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BasePath = 'scripts/Publish-Discover-GPIOrderIntakeHistoricalIdentityDiagnostics-0.1.0.10-PRE.ps1'
$ExpectedBaseBlob = '260fe4ca53bdd82b356d2926b49fdc0fe1d0aa70'
$ExpectedOrderApiBlob = '3da979196e524b64dd0d3033173356fd82cb17d3'
$ExpectedAuthorityBlob = 'a18a137fdbdc65b2b302cae66f374da5301fa371'
$ExpectedResolverBlob = '756cb0da34b4f96442bf72b8148c681cdce0ee3c'
$ExpectedCreateApiBlob = 'bff26d78fdd894aae6da3dab5a9c7ccf06d17036'
$ExpectedPackageHash = 'E479223156182663E4FF712A467CE479F5037038E100363C94C9DDE99FA29BBB'

Push-Location $RepoRoot
try {
    $headBaseBlob = (& git rev-parse "HEAD:$BasePath").Trim()
    if ($LASTEXITCODE -ne 0 -or $headBaseBlob -ne $ExpectedBaseBlob) {
        throw "Committed base harness changed. Expected $ExpectedBaseBlob; got $headBaseBlob."
    }

    $blobChecks = @(
        [pscustomobject]@{ Path='order-intake-bc/src/Page71201.GPIOrderIntakeOrderAPI.al'; Expected=$ExpectedOrderApiBlob; Label='Order API 71201' },
        [pscustomobject]@{ Path='order-intake-bc/src/Codeunit71200.GPIOrderIntakeAuthority.al'; Expected=$ExpectedAuthorityBlob; Label='Authority' },
        [pscustomobject]@{ Path='order-intake-bc/src/Codeunit71201.GPIOrderIntakeResolver.al'; Expected=$ExpectedResolverBlob; Label='Resolver' },
        [pscustomobject]@{ Path='order-intake-bc/src/Page71200.GPIOrderIntakeCustomerAPI.al'; Expected=$ExpectedCreateApiBlob; Label='Create API' }
    )
    foreach ($check in $blobChecks) {
        $actual = (& git rev-parse "HEAD:$($check.Path)").Trim()
        if ($LASTEXITCODE -ne 0 -or $actual -ne $check.Expected) {
            throw "$($check.Label) blob changed. Expected $($check.Expected); got $actual."
        }
    }

    $orderApi = (& git show 'HEAD:order-intake-bc/src/Page71201.GPIOrderIntakeOrderAPI.al') -join "`n"
    foreach ($marker in @(
        'InsertAllowed = false;',
        'ModifyAllowed = false;',
        'DeleteAllowed = false;',
        'field(requestedDeliveryDate; Rec."Requested Delivery Date")',
        'field(promisedDeliveryDate; Rec."Promised Delivery Date")',
        'field(shipToCode; Rec."Ship-to Code")',
        'field(shipmentMethodCode; Rec."Shipment Method Code")',
        'field(shippingAgentCode; Rec."Shipping Agent Code")',
        'field(shippingAgentServiceCode; Rec."Shipping Agent Service Code")',
        'field(shippingTime; Rec."Shipping Time")',
        'field(outboundWarehouseHandlingTime; Rec."Outbound Whse. Handling Time")'
    )) {
        if ($orderApi.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) {
            throw "0.1.0.11 read-only Order API marker missing: $marker"
        }
    }

    $source = (& git show "HEAD:$BasePath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($source)) { throw 'Committed base harness content was empty.' }

    $entityOld = 'return "$customRoot/$EntitySet?`$filter=$encoded"'
    $entityNew = 'return "$customRoot/${EntitySet}?`$filter=$encoded"'
    $entityPatchCount = ([regex]::Matches($source,[regex]::Escape($entityOld))).Count
    if ($entityPatchCount -ne 1) { throw "Expected one EntitySet interpolation patch target; found $entityPatchCount." }
    $source = $source.Replace($entityOld,$entityNew)

    $versionPatchCount = ([regex]::Matches($source,[regex]::Escape('0.1.0.10'))).Count
    if ($versionPatchCount -lt 5) { throw "Unexpected 0.1.0.10 marker count in base harness: $versionPatchCount." }
    $source = $source.Replace('0.1.0.10','0.1.0.11')

    $oldHash = 'C398F0D44795FCF1111F8E4C32E9B94052CF96BA7900A4990DF91F66845BADB0'
    $hashPatchCount = ([regex]::Matches($source,[regex]::Escape($oldHash))).Count
    if ($hashPatchCount -ne 1) { throw "Expected one prior package-hash marker; found $hashPatchCount." }
    $source = $source.Replace($oldHash,$ExpectedPackageHash)

    $priorOld = "if (`$v -notin @('0.1.0.9'))"
    $priorNew = "if (`$v -notin @('0.1.0.10'))"
    $priorPatchCount = ([regex]::Matches($source,[regex]::Escape($priorOld))).Count
    if ($priorPatchCount -ne 1) { throw "Expected one prior-version allow-list patch target; found $priorPatchCount." }
    $source = $source.Replace($priorOld,$priorNew)

    $append = @'

# ---------------------------------------------------------------------------------------------------------------------
# 0.1.0.11 current Sales Header date / shipping diagnostics - GET ONLY.
# ---------------------------------------------------------------------------------------------------------------------
Write-Host ''
Write-Host 'HERDEZ_CURRENT_ORDER_DATE_SHIPPING_AUTHORITY' -ForegroundColor Cyan
$herdezDateTargets = @(
    [pscustomobject]@{ SalesOrder='117357'; CustomerPo='4500063632'; SourceDelivery='2026-09-01' },
    [pscustomobject]@{ SalesOrder='117358'; CustomerPo='4500063739'; SourceDelivery='2026-09-01' },
    [pscustomobject]@{ SalesOrder='117371'; CustomerPo='4500063770'; SourceDelivery='2026-10-01' }
)
$herdezDateRows = [System.Collections.Generic.List[object]]::new()
foreach ($target in $herdezDateTargets) {
    $soLit = Escape-ODataLiteral ([string]$target.SalesOrder)
    $filter = "number eq '$soLit' and customerNumber eq 'HERDEZ'"
    $rows = @(Invoke-BcGetAll (New-FilterUri 'orderIntakeOrders' $filter) $headers)
    if ($rows.Count -ne 1) {
        throw "Expected exactly one HERDEZ Sales Order $($target.SalesOrder); found $($rows.Count)."
    }
    $row = $rows[0]
    if ([string]$row.externalDocumentNumber -ne [string]$target.CustomerPo) {
        throw "HERDEZ Sales Order $($target.SalesOrder) external-document mismatch: $($row.externalDocumentNumber)."
    }
    $sourceDelivery = [DateTime]::ParseExact([string]$target.SourceDelivery,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture).Date
    $requested = if ([string]::IsNullOrWhiteSpace([string]$row.requestedDeliveryDate)) { $null } else { [DateTime]$row.requestedDeliveryDate }
    $promised = if ([string]::IsNullOrWhiteSpace([string]$row.promisedDeliveryDate)) { $null } else { [DateTime]$row.promisedDeliveryDate }
    $shipment = if ([string]::IsNullOrWhiteSpace([string]$row.shipmentDate)) { $null } else { [DateTime]$row.shipmentDate }
    $requestedMatch = ($null -ne $requested -and $requested.Date -eq $sourceDelivery)
    $promisedMatch = ($null -ne $promised -and $promised.Date -eq $sourceDelivery)
    $shipmentMatch = ($null -ne $shipment -and $shipment.Date -eq $sourceDelivery)
    $leadDays = if ($null -ne $shipment) { [int](($sourceDelivery - $shipment.Date).TotalDays) } else { $null }

    Write-Host ('HERDEZ_ORDER_DATE_ROW|so={0}|external={1}|orderDate={2}|documentDate={3}|sourceDelivery={4}|requestedDelivery={5}|promisedDelivery={6}|shipmentDate={7}|sourceEqualsRequested={8}|sourceEqualsPromised={9}|sourceEqualsShipment={10}|shipmentToDeliveryCalendarDays={11}|shipTo={12}|shipName={13}|shipAddr1={14}|shipCity={15}|shipPostal={16}|shipCountry={17}|shipmentMethod={18}|shippingAgent={19}|shippingAgentService={20}|shippingTime={21}|outboundHandling={22}|location={23}|status={24}' -f
        $row.number,$row.externalDocumentNumber,$row.orderDate,$row.documentDate,$target.SourceDelivery,$row.requestedDeliveryDate,$row.promisedDeliveryDate,$row.shipmentDate,$requestedMatch,$promisedMatch,$shipmentMatch,$leadDays,$row.shipToCode,$row.shipToName,$row.shipToAddressLine1,$row.shipToCity,$row.shipToPostalCode,$row.shipToCountryCode,$row.shipmentMethodCode,$row.shippingAgentCode,$row.shippingAgentServiceCode,$row.shippingTime,$row.outboundWarehouseHandlingTime,$row.locationCode,$row.status)

    $herdezDateRows.Add([pscustomobject]@{
        salesOrder = [string]$row.number
        customerPo = [string]$row.externalDocumentNumber
        sourceDelivery = [string]$target.SourceDelivery
        requestedDelivery = [string]$row.requestedDeliveryDate
        promisedDelivery = [string]$row.promisedDeliveryDate
        shipmentDate = [string]$row.shipmentDate
        sourceEqualsRequested = $requestedMatch
        sourceEqualsPromised = $promisedMatch
        sourceEqualsShipment = $shipmentMatch
        shipmentToDeliveryCalendarDays = $leadDays
        shipToCode = [string]$row.shipToCode
        shipmentMethodCode = [string]$row.shipmentMethodCode
        shippingAgentCode = [string]$row.shippingAgentCode
        shippingAgentServiceCode = [string]$row.shippingAgentServiceCode
        shippingTime = [string]$row.shippingTime
        outboundWarehouseHandlingTime = [string]$row.outboundWarehouseHandlingTime
        locationCode = [string]$row.locationCode
        status = [string]$row.status
    })
}

$requestedMatches = @($herdezDateRows | Where-Object { $_.sourceEqualsRequested }).Count
$promisedMatches = @($herdezDateRows | Where-Object { $_.sourceEqualsPromised }).Count
$shipmentMatches = @($herdezDateRows | Where-Object { $_.sourceEqualsShipment }).Count
$leadSet = @($herdezDateRows | ForEach-Object { $_.shipmentToDeliveryCalendarDays } | Where-Object { $null -ne $_ } | Sort-Object -Unique)
Write-Host ('HERDEZ_ORDER_DATE_SUMMARY|rows={0}|sourceEqualsRequested={1}|sourceEqualsPromised={2}|sourceEqualsShipment={3}|shipmentToDeliveryCalendarDays={4}' -f $herdezDateRows.Count,$requestedMatches,$promisedMatches,$shipmentMatches,($leadSet -join ','))

Write-Host ''
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE 0.1.0.11 CURRENT ORDER DATE / SHIPPING DIAGNOSTICS RESULT' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'Extension install      : PASS / exact PRE 0.1.0.11'
Write-Host 'Current order reads    : PASS / GET ONLY'
Write-Host 'Authority behavior     : UNCHANGED / certified blob'
Write-Host 'Giovanni resolver      : UNCHANGED / certified blob'
Write-Host 'Business-data writes   : NONE' -ForegroundColor Green
Write-Host 'Sales-order action     : NOT CALLED' -ForegroundColor Green
Write-Host 'Write authorization    : NOT GRANTED' -ForegroundColor Green
Write-Host 'Production             : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

[pscustomobject]@{
    success = $true
    environment = $Environment
    environmentType = $environmentType
    company = $CompanyName
    installedApp = "$ExpectedAppName $ExpectedAppVersion"
    packageSha256 = $actualHash
    herdezDateRows = @($herdezDateRows)
    sourceDeliveryEqualsRequested = $requestedMatches
    sourceDeliveryEqualsPromised = $promisedMatches
    sourceDeliveryEqualsShipment = $shipmentMatches
    shipmentToDeliveryCalendarDays = $leadSet
    writeAuthorization = 'NOT_GRANTED'
    safety = [ordered]@{
        extensionMutation = 'EXACT_0.1.0.11_PRE_UPGRADE_ONLY'
        businessDataReads = 'GET_ONLY_AFTER_INSTALL'
        businessDataWrites = 'NONE'
        salesOrderAction = 'NOT_CALLED'
        releaseShipInvoicePost = 'NOT_CALLED_BLOCKED'
        production = 'HARD_BLOCKED'
    }
} | ConvertTo-Json -Depth 10
'@
    $source = $source + $append

    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
    $parseErrors = @($parseErrors)
    if ($parseErrors.Count -ne 0) {
        foreach ($e in $parseErrors) {
            Write-Host ("PARSE_ERROR|message={0}|text={1}" -f $e.Message,$e.Extent.Text) -ForegroundColor Red
        }
        throw "0.1.0.11 publish/read harness has $($parseErrors.Count) PowerShell parse error(s). BC was not contacted."
    }

    $suspiciousVars = @($ast.FindAll({
        param($node)
        if ($node -isnot [System.Management.Automation.Language.VariableExpressionAst]) { return $false }
        $name = [string]$node.VariablePath.UserPath
        return $name.EndsWith('?',[StringComparison]::Ordinal) -or $name.EndsWith(':',[StringComparison]::Ordinal)
    },$true))
    if ($suspiciousVars.Count -ne 0) {
        foreach ($v in $suspiciousVars) {
            Write-Host ("STRICTMODE_VARIABLE_REJECT|name={0}|text={1}" -f $v.VariablePath.UserPath,$v.Extent.Text) -ForegroundColor Red
        }
        throw "0.1.0.11 publish/read harness contains $($suspiciousVars.Count) suspicious StrictMode variable token(s). BC was not contacted."
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.11 - ORDER DATE / SHIPPING DIAGNOSTICS GUARDED PUBLISH + READ' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed base blob      : $ExpectedBaseBlob"
    Write-Host "Order API blob           : $ExpectedOrderApiBlob / READ ONLY"
    Write-Host "Authority blob           : $ExpectedAuthorityBlob / UNCHANGED"
    Write-Host "Resolver blob            : $ExpectedResolverBlob / UNCHANGED"
    Write-Host "Create API blob          : $ExpectedCreateApiBlob / UNCHANGED"
    Write-Host "EntitySet patch target   : $entityPatchCount / 1"
    Write-Host "Version patch markers    : $versionPatchCount"
    Write-Host "Prior-version patch      : $priorPatchCount / 1"
    Write-Host "Package SHA256           : $ExpectedPackageHash"
    Write-Host 'PowerShell syntax gate   : PASS' -ForegroundColor Green
    Write-Host 'StrictMode variable gate : PASS' -ForegroundColor Green
    Write-Host 'Extension mutation       : EXACT PRE 0.1.0.11 upgrade only' -ForegroundColor Yellow
    Write-Host 'Business-data reads      : GET ONLY after install' -ForegroundColor Green
    Write-Host 'Business-data writes     : NONE' -ForegroundColor Green
    Write-Host 'Sales-order action       : NOT PRESENT' -ForegroundColor Green
    Write-Host 'Production               : HARD BLOCKED' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $tempPath = Join-Path $PSScriptRoot ('.GPIOrderIntake-OrderDateDiagnostics-0.1.0.11-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $tempPath -Value $source -Encoding utf8NoBOM -NoNewline
        & $tempPath -EnableInstall
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "0.1.0.11 publish/read harness exited with code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
