#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedBaseBlob = '127c6841c271747de42456959b148bb7899a51bc'
$BasePath = 'scripts/Build-GPIOrderIntakeResolverAL-PRE.ps1'
$TargetVersion = '0.1.0.9'

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
    $itemRefPath = 'order-intake-bc/src/Page71209.GPIOrderIntakeItemReferenceAPI.al'
    $shipToPath = 'order-intake-bc/src/Page71210.GPIOrderIntakeShipToAPI.al'
    $permissionPath = 'order-intake-bc/src/PermissionSet71200.GPIOrderIntake.al'

    foreach ($path in @($appPath,$itemRefPath,$shipToPath,$permissionPath)) {
        $blob = (& git rev-parse "HEAD:$path").Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($blob)) {
            throw "Required committed 0.1.0.9 source missing at HEAD:$path"
        }
    }

    $app = (& git show "HEAD:$appPath") -join "`n" | ConvertFrom-Json
    if ([string]$app.version -ne $TargetVersion) { throw "Expected app version $TargetVersion; got $($app.version)." }

    $itemRef = (& git show "HEAD:$itemRefPath") -join "`n"
    $shipTo = (& git show "HEAD:$shipToPath") -join "`n"
    $permissions = (& git show "HEAD:$permissionPath") -join "`n"

    $readOnlyPages = @(
        [pscustomobject]@{Name='Item Reference';Text=$itemRef;Source='SourceTable = "Item Reference";'},
        [pscustomobject]@{Name='Ship-to Address';Text=$shipTo;Source='SourceTable = "Ship-to Address";'}
    )
    foreach ($page in $readOnlyPages) {
        if ($page.Text.IndexOf($page.Source,[StringComparison]::Ordinal) -lt 0) { throw "$($page.Name) source-table gate failed." }
        foreach ($marker in @('InsertAllowed = false;','ModifyAllowed = false;','DeleteAllowed = false;')) {
            if ($page.Text.IndexOf($marker,[StringComparison]::Ordinal) -lt 0) { throw "$($page.Name) read-only marker missing: $marker" }
        }
    }
    foreach ($marker in @('tabledata "Item Reference" = R','tabledata "Ship-to Address" = R','page "GPI Order Intake Item Ref" = X','page "GPI Order Intake Ship-To" = X')) {
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
    $patched = $patched.Replace('GPI ORDER INTAKE 0.1.0.7 RESOLVER - PRE SYMBOL GET + LOCAL COMPILE ONLY','GPI ORDER INTAKE 0.1.0.9 IDENTITY DIAGNOSTICS - PRE SYMBOL GET + LOCAL COMPILE ONLY')

    if ($patched -match '0\.1\.0\.7') { throw 'Old resolver version remains after patch.' }
    if ($patched.IndexOf($newMarker,[StringComparison]::OrdinalIgnoreCase) -lt 0) { throw 'Variable-quantity pricing-context marker missing.' }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.9 IDENTITY DIAGNOSTICS - COMPILE ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed base blob : $headBlob"
    Write-Host "Version patches     : $versionCount / 4"
    Write-Host "Resolver marker     : $markerCount / 1"
    Write-Host 'New API 71209       : Item Reference / READ ONLY'
    Write-Host 'New API 71210       : Ship-to Address / READ ONLY'
    Write-Host 'Resolver behavior   : UNCHANGED from 0.1.0.8'
    Write-Host 'Publish / install   : NONE' -ForegroundColor Green
    Write-Host 'Business-data write : NONE' -ForegroundColor Green
    Write-Host 'Sales-order action  : NOT CALLED' -ForegroundColor Green
    Write-Host 'Production          : HARD BLOCKED' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $temp = Join-Path $PSScriptRoot ('.GPIOrderIntake-IdentityBuild-0.1.0.9-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $temp -Value $patched -Encoding UTF8 -NoNewline
        & $temp
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "0.1.0.9 compile harness exited with code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
