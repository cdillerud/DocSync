#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedBaseBlob       = '127c6841c271747de42456959b148bb7899a51bc'
$ExpectedAuthorityBlob  = 'a18a137fdbdc65b2b302cae66f374da5301fa371'
$ExpectedResolverBlob   = '756cb0da34b4f96442bf72b8148c681cdce0ee3c'
$ExpectedCustomerApiBlob= 'bff26d78fdd894aae6da3dab5a9c7ccf06d17036'
$BasePath               = 'scripts/Build-GPIOrderIntakeResolverAL-PRE.ps1'
$TargetVersion          = '0.1.0.11'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $RepoRoot
try {
    function Get-HeadBlob {
        param([Parameter(Mandatory)][string]$Path)
        $blob = (& git rev-parse "HEAD:$Path").Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($blob)) {
            throw "Could not resolve committed file at HEAD:$Path"
        }
        return $blob
    }

    $headBase = Get-HeadBlob $BasePath
    if ($headBase -ne $ExpectedBaseBlob) {
        throw "Committed compile harness changed. Expected $ExpectedBaseBlob; got $headBase."
    }

    $appPath       = 'order-intake-bc/app.json'
    $orderApiPath  = 'order-intake-bc/src/Page71201.GPIOrderIntakeOrderAPI.al'
    $authorityPath = 'order-intake-bc/src/Codeunit71200.GPIOrderIntakeAuthority.al'
    $resolverPath  = 'order-intake-bc/src/Codeunit71201.GPIOrderIntakeResolver.al'
    $customerApiPath = 'order-intake-bc/src/Page71200.GPIOrderIntakeCustomerAPI.al'

    foreach ($path in @($appPath,$orderApiPath,$authorityPath,$resolverPath,$customerApiPath)) {
        [void](Get-HeadBlob $path)
    }

    $authorityBlob = Get-HeadBlob $authorityPath
    $resolverBlob = Get-HeadBlob $resolverPath
    $customerApiBlob = Get-HeadBlob $customerApiPath
    if ($authorityBlob -ne $ExpectedAuthorityBlob) {
        throw "WRITE-PATH SAFETY STOP: authority blob changed. Expected $ExpectedAuthorityBlob; got $authorityBlob."
    }
    if ($resolverBlob -ne $ExpectedResolverBlob) {
        throw "RESOLVER SAFETY STOP: resolver blob changed. Expected $ExpectedResolverBlob; got $resolverBlob."
    }
    if ($customerApiBlob -ne $ExpectedCustomerApiBlob) {
        throw "WRITE-PATH SAFETY STOP: bound create API blob changed. Expected $ExpectedCustomerApiBlob; got $customerApiBlob."
    }

    $app = (& git show "HEAD:$appPath") -join "`n" | ConvertFrom-Json
    if ([string]$app.version -ne $TargetVersion) {
        throw "Expected app version $TargetVersion; got $($app.version)."
    }

    $orderApi = (& git show "HEAD:$orderApiPath") -join "`n"
    foreach ($marker in @(
        'SourceTable = "Sales Header";',
        'SourceTableView = where("Document Type" = const(Order));',
        'InsertAllowed = false;',
        'ModifyAllowed = false;',
        'DeleteAllowed = false;'
    )) {
        if ($orderApi.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) {
            throw "Read-only Sales Order API marker missing: $marker"
        }
    }

    $fieldMarkers = @(
        'field(requestedDeliveryDate; Rec."Requested Delivery Date")',
        'field(promisedDeliveryDate; Rec."Promised Delivery Date")',
        'field(shipmentDate; Rec."Shipment Date")',
        'field(shipToCode; Rec."Ship-to Code")',
        'field(shipToAddressLine1; Rec."Ship-to Address")',
        'field(shipToPostalCode; Rec."Ship-to Post Code")',
        'field(shipmentMethodCode; Rec."Shipment Method Code")',
        'field(shippingAgentCode; Rec."Shipping Agent Code")',
        'field(shippingAgentServiceCode; Rec."Shipping Agent Service Code")',
        'field(shippingTime; Rec."Shipping Time")',
        'field(outboundWarehouseHandlingTime; Rec."Outbound Whse. Handling Time")'
    )
    foreach ($marker in $fieldMarkers) {
        if ($orderApi.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) {
            throw "Required 0.1.0.11 date/shipping diagnostic field missing: $marker"
        }
    }

    $base = (& git show "HEAD:$BasePath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($base)) { throw 'Committed compile harness content was empty.' }

    $versionCount = ([regex]::Matches($base,[regex]::Escape('0.1.0.7'))).Count
    if ($versionCount -ne 4) { throw "Expected exactly 4 version markers; found $versionCount." }

    $oldResolverMarker = 'two most recent exact-context posted invoices disagree'
    $newResolverMarker = 'two most recent pricing-context posted invoices disagree'
    $resolverMarkerCount = ([regex]::Matches($base,[regex]::Escape($oldResolverMarker))).Count
    if ($resolverMarkerCount -ne 1) {
        throw "Expected exactly one resolver source marker; found $resolverMarkerCount."
    }

    $patched = $base.Replace('0.1.0.7',$TargetVersion).Replace($oldResolverMarker,$newResolverMarker)
    $patched = $patched.Replace(
        'GPI ORDER INTAKE 0.1.0.7 RESOLVER - PRE SYMBOL GET + LOCAL COMPILE ONLY',
        'GPI ORDER INTAKE 0.1.0.11 ORDER DATE DIAGNOSTICS - PRE SYMBOL GET + LOCAL COMPILE ONLY'
    )

    if ($patched -match '0\.1\.0\.7') { throw 'Old resolver version remains after patch.' }
    if ($patched.IndexOf($newResolverMarker,[StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw 'Variable-quantity pricing-context marker missing after patch.'
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.11 ORDER DATE / SHIPPING DIAGNOSTICS - COMPILE ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed base blob : $headBase"
    Write-Host "Version patches     : $versionCount / 4"
    Write-Host "Resolver marker     : $resolverMarkerCount / 1"
    Write-Host "Authority blob      : PASS / unchanged $authorityBlob"
    Write-Host "Resolver blob       : PASS / unchanged $resolverBlob"
    Write-Host "Create API blob     : PASS / unchanged $customerApiBlob"
    Write-Host 'Order API 71201      : Sales Header / READ ONLY'
    Write-Host 'New fields           : requested/promised delivery + ship-to + shipping method/agent/time / READ ONLY'
    Write-Host 'Resolver behavior    : UNCHANGED from 0.1.0.8'
    Write-Host 'Create behavior      : UNCHANGED from 0.1.0.10'
    Write-Host 'Publish / install    : NONE' -ForegroundColor Green
    Write-Host 'Business-data read   : NONE' -ForegroundColor Green
    Write-Host 'Business-data write  : NONE' -ForegroundColor Green
    Write-Host 'Sales-order action   : NOT CALLED' -ForegroundColor Green
    Write-Host 'Production           : HARD BLOCKED' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $temp = Join-Path $PSScriptRoot ('.GPIOrderIntake-OrderDateDiagnostics-0.1.0.11-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $temp -Value $patched -Encoding UTF8 -NoNewline
        & $temp
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "0.1.0.11 compile harness exited with code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
