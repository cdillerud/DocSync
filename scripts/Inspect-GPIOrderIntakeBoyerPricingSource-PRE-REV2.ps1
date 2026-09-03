#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# REV2 WRAPPER FOR BOYER PRICING SOURCE INSPECTION
# Purpose: apply one vetted local-only PowerShell binding repair to the committed source inspector, run it, then clean up.
# BC behavior is inherited unchanged from the verified GET-only source inspector.
# =====================================================================================================================

$SourceScript = Join-Path $PSScriptRoot 'Inspect-GPIOrderIntakeBoyerPricingSource-PRE.ps1'
$ExpectedBlob = '752e949da03ca3f942dacc14e1d8478c252dc1e2'

if (-not (Test-Path -LiteralPath $SourceScript)) {
    throw "Required source inspector not found: $SourceScript"
}

$git = Get-Command git -ErrorAction Stop
$ActualBlob = (& $git.Source hash-object -- $SourceScript).Trim()

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - BOYER PRICING SOURCE INSPECTION REV2 / LOCAL BINDING REPAIR' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Expected source blob : $ExpectedBlob"
Write-Host "Actual source blob   : $ActualBlob"

if ($ActualBlob -ne $ExpectedBlob) {
    throw 'Source inspector blob does not match the vetted revision. Stopping.'
}

Write-Host 'Source blob verification: PASS' -ForegroundColor Green
Write-Host 'Patch scope             : Allow empty strings inside AL source line arrays only'
Write-Host 'BC mutation             : NONE'
Write-Host 'Sales-order action      : NOT CALLED'
Write-Host ('=' * 120) -ForegroundColor Cyan

$source = [System.IO.File]::ReadAllText($SourceScript, [System.Text.Encoding]::UTF8)
$old = '[Parameter(Mandatory)][string[]]$Lines,'
$new = '[Parameter(Mandatory)][AllowEmptyString()][string[]]$Lines,'

$occurrences = ([regex]::Matches($source, [regex]::Escape($old))).Count
if ($occurrences -ne 1) {
    throw "Expected exactly one Lines parameter binding to patch; found $occurrences."
}

$patched = $source.Replace($old, $new)
if ($patched -eq $source) {
    throw 'REV2 local patch did not change the source. Stopping.'
}

$tempPath = Join-Path ([System.IO.Path]::GetTempPath()) ("GPIOrderIntake-BoyerPricingSource-REV2-" + [guid]::NewGuid().ToString('N') + '.ps1')

try {
    [System.IO.File]::WriteAllText($tempPath, $patched, [System.Text.UTF8Encoding]::new($false))
    Write-Host 'REV2 narrow patch       : PASS' -ForegroundColor Green
    Write-Host 'Starting patched GET-only source inspection...' -ForegroundColor Cyan
    Write-Host ''

    & $tempPath

    if (-not $?) {
        throw 'Patched Boyer pricing source inspector returned a failing status.'
    }
}
finally {
    Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'GPI ORDER INTAKE BOYER PRICING SOURCE INSPECTION REV2: LOCAL PATCH WRAPPER COMPLETE' -ForegroundColor Green
