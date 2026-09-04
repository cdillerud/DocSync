#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Compile-only wrapper for the variable-quantity 0.1.0.8 resolver.
# Reads the proven compile harness from the committed Git object, never from a modified working-tree copy.
$ExpectedBaseBlob = '127c6841c271747de42456959b148bb7899a51bc'
$BasePath = 'scripts/Build-GPIOrderIntakeResolverAL-PRE.ps1'
$TargetVersion = '0.1.0.8'

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

    $base = (& git show "HEAD:$BasePath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($base)) { throw 'Committed compile harness content was empty.' }

    $versionCount = ([regex]::Matches($base, [regex]::Escape('0.1.0.7'))).Count
    if ($versionCount -ne 4) { throw "Expected exactly 4 version markers; found $versionCount." }

    $oldMarker = 'two most recent exact-context posted invoices disagree'
    $newMarker = 'two most recent pricing-context posted invoices disagree'
    $markerCount = ([regex]::Matches($base, [regex]::Escape($oldMarker))).Count
    if ($markerCount -ne 1) { throw "Expected exactly one resolver source marker; found $markerCount." }

    $patched = $base.Replace('0.1.0.7', $TargetVersion).Replace($oldMarker, $newMarker)

    if ($patched -match '0\.1\.0\.7') { throw 'Old resolver version remains after patch.' }
    if ($patched.IndexOf($newMarker, [StringComparison]::OrdinalIgnoreCase) -lt 0) { throw 'Variable-quantity pricing-context marker missing.' }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 VARIABLE-QUANTITY RESOLVER - COMPILE ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed base blob : $headBlob"
    Write-Host "Version patches     : $versionCount / 4"
    Write-Host "Pricing-key patch   : $markerCount / 1"
    Write-Host 'Architecture        : incoming PO owns quantity; price key excludes quantity'
    Write-Host 'Publish / install   : NONE'
    Write-Host 'Business-data write : NONE'
    Write-Host 'Sales-order action  : NOT CALLED'
    Write-Host 'Production          : HARD BLOCKED'
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $temp = Join-Path $PSScriptRoot ('.GPIOrderIntake-ResolverBuild-0.1.0.8-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $temp -Value $patched -Encoding UTF8 -NoNewline
        & $temp
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "0.1.0.8 compile harness exited with code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
