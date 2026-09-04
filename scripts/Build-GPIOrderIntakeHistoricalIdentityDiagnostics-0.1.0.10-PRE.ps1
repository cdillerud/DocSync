#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedBaseBlob = '127c6841c271747de42456959b148bb7899a51bc'
$BasePath = 'scripts/Build-GPIOrderIntakeResolverAL-PRE.ps1'
$TargetVersion = '0.1.0.10'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $RepoRoot
try {
    $headBlob = (& git rev-parse "HEAD:$BasePath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($headBlob)) {
        throw "Could not resolve committed compile harness at HEAD:$BasePath"
    }
    if ($headBlob -ne $ExpectedBaseBlob) {
        throw "Committed compile harness changed. Expected $ExpectedBaseBlob; got $headBlob."
    }

    $appPath = 'order-intake-bc/app.json'
    $permissionPath = 'order-intake-bc/src/PermissionSet71200.GPIOrderIntake.al'
    $invoiceLinePath = 'order-intake-bc/src/Page71208.GPIOrderIntakeSalesInvoiceLineHistoryAPI.al'
    $headerArchivePath = 'order-intake-bc/src/Page71211.GPIOrderIntakeSalesHeaderArchiveAPI.al'
    $lineArchivePath = 'order-intake-bc/src/Page71212.GPIOrderIntakeSalesLineArchiveAPI.al'
    $invoiceHeaderPath = 'order-intake-bc/src/Page71213.GPIOrderIntakeSalesInvoiceHeaderAPI.al'

    foreach ($path in @($appPath,$permissionPath,$invoiceLinePath,$headerArchivePath,$lineArchivePath,$invoiceHeaderPath)) {
        $blob = (& git rev-parse "HEAD:$path").Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($blob)) {
            throw "Required committed 0.1.0.10 source missing at HEAD:$path"
        }
    }

    $app = (& git show "HEAD:$appPath") -join "`n" | ConvertFrom-Json
    if ([string]$app.version -ne $TargetVersion) { throw "Expected app version $TargetVersion; got $($app.version)." }

    $permissions = (& git show "HEAD:$permissionPath") -join "`n"
    $invoiceLine = (& git show "HEAD:$invoiceLinePath") -join "`n"
    $headerArchive = (& git show "HEAD:$headerArchivePath") -join "`n"
    $lineArchive = (& git show "HEAD:$lineArchivePath") -join "`n"
    $invoiceHeader = (& git show "HEAD:$invoiceHeaderPath") -join "`n"

    $readOnlyPages = @(
        [pscustomobject]@{Name='Sales Header Archive';Text=$headerArchive;Source='SourceTable = "Sales Header Archive";'},
        [pscustomobject]@{Name='Sales Line Archive';Text=$lineArchive;Source='SourceTable = "Sales Line Archive";'},
        [pscustomobject]@{Name='Posted Sales Invoice Header';Text=$invoiceHeader;Source='SourceTable = "Sales Invoice Header";'},
        [pscustomobject]@{Name='Posted Sales Invoice Line';Text=$invoiceLine;Source='SourceTable = "Sales Invoice Line";'}
    )
    foreach ($page in $readOnlyPages) {
        if ($page.Text.IndexOf($page.Source,[StringComparison]::Ordinal) -lt 0) { throw "$($page.Name) source-table gate failed." }
        foreach ($marker in @('InsertAllowed = false;','ModifyAllowed = false;','DeleteAllowed = false;')) {
            if ($page.Text.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) { throw "$($page.Name) read-only marker missing: $marker" }
        }
    }

    foreach ($marker in @(
        'field(itemReferenceNumber; Rec."Item Reference No.")',
        'field(itemReferenceUnitOfMeasure; Rec."Item Reference Unit of Measure")',
        'field(itemReferenceType; Rec."Item Reference Type")',
        'field(itemReferenceTypeNumber; Rec."Item Reference Type No.")'
    )) {
        if ($invoiceLine.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) { throw "Posted invoice-line reference marker missing: $marker" }
        if ($lineArchive.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) { throw "Archived sales-line reference marker missing: $marker" }
    }

    foreach ($marker in @(
        'tabledata "Sales Header Archive" = R',
        'tabledata "Sales Line Archive" = R',
        'tabledata "Sales Invoice Header" = R',
        'tabledata "Sales Invoice Line" = R',
        'page "GPI Order Intake SalesHdrArc" = X',
        'page "GPI Order Intake SalesLineArc" = X',
        'page "GPI Order Intake InvHdr Hist" = X'
    )) {
        if ($permissions.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) { throw "Permission marker missing: $marker" }
    }

    $base = (& git show "HEAD:$BasePath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($base)) { throw 'Committed compile harness content was empty.' }

    $versionCount = ([regex]::Matches($base, [regex]::Escape('0.1.0.7'))).Count
    if ($versionCount -ne 4) { throw "Expected exactly 4 version markers; found $versionCount." }

    $oldMarker = 'two most recent exact-context posted invoices disagree'
    $newMarker = 'two most recent pricing-context posted invoices disagree'
    $markerCount = ([regex]::Matches($base, [regex]::Escape($oldMarker))).Count
    if ($markerCount -ne 1) { throw "Expected exactly one resolver source marker; found $markerCount." }

    $patched = $base.Replace('0.1.0.7', $TargetVersion).Replace($oldMarker, $newMarker)
    $patched = $patched.Replace(
        'GPI ORDER INTAKE 0.1.0.7 RESOLVER - PRE SYMBOL GET + LOCAL COMPILE ONLY',
        'GPI ORDER INTAKE 0.1.0.10 HISTORICAL IDENTITY DIAGNOSTICS - PRE SYMBOL GET + LOCAL COMPILE ONLY'
    )

    if ($patched -match '0\.1\.0\.7') { throw 'Old resolver version remains after patch.' }
    if ($patched.IndexOf($newMarker,[StringComparison]::OrdinalIgnoreCase) -lt 0) { throw 'Variable-quantity pricing-context marker missing.' }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.10 HISTORICAL IDENTITY DIAGNOSTICS - COMPILE ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed base blob : $headBlob"
    Write-Host "Version patches     : $versionCount / 4"
    Write-Host "Resolver marker     : $markerCount / 1"
    Write-Host 'API 71208           : Posted Sales Invoice Line + retained Item Reference / READ ONLY'
    Write-Host 'API 71211           : Sales Header Archive / READ ONLY'
    Write-Host 'API 71212           : Sales Line Archive + retained Item Reference / READ ONLY'
    Write-Host 'API 71213           : Posted Sales Invoice Header / READ ONLY'
    Write-Host 'Resolver behavior   : UNCHANGED from 0.1.0.8'
    Write-Host 'Publish / install   : NONE' -ForegroundColor Green
    Write-Host 'Business-data write : NONE' -ForegroundColor Green
    Write-Host 'Sales-order action  : NOT CALLED' -ForegroundColor Green
    Write-Host 'Production          : HARD BLOCKED' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $temp = Join-Path $PSScriptRoot ('.GPIOrderIntake-HistoricalIdentityBuild-0.1.0.10-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $temp -Value $patched -Encoding UTF8 -NoNewline
        & $temp
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "0.1.0.10 compile harness exited with code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
