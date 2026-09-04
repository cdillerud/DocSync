#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# GPI ORDER INTAKE - BOYER SYMBOL PACKAGE INSPECTION REV4
# Narrow local repair wrapper around the vetted REV3 NAVX-aware GET-only probe.
#
# This wrapper:
#   1. verifies the exact committed REV3 Git blob,
#   2. patches only Add-TermHits Destination to allow an initially-empty generic list,
#   3. executes the patched temporary copy,
#   4. deletes the temporary copy.
#
# It adds no Business Central calls or write capability of its own.
# =====================================================================================================================

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Rev3Path = Join-Path $PSScriptRoot 'Inspect-GPIOrderIntakeBoyerSymbols-PRE-REV3.ps1'
$ExpectedRev3Blob = '34f5a43647badee30811de5dc48516efdd17f335'

if (-not (Test-Path -LiteralPath $Rev3Path -PathType Leaf)) {
    throw "Required REV3 script not found: $Rev3Path"
}

$git = Get-Command git -ErrorAction Stop
$actualBlob = (& $git.Source -C $RepoRoot hash-object -- $Rev3Path).Trim()
if ($LASTEXITCODE -ne 0) {
    throw 'git hash-object failed while verifying REV3.'
}

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - BOYER SYMBOL PACKAGE INSPECTION REV4 / EMPTY-LIST BINDING FIX' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "REV3 path         : $Rev3Path"
Write-Host "Expected REV3 blob: $ExpectedRev3Blob"
Write-Host "Actual REV3 blob  : $actualBlob"
Write-Host 'Patch scope        : Add-TermHits Destination -> AllowEmptyCollection only'
Write-Host 'BC capability      : UNCHANGED FROM REV3 / GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation : NONE' -ForegroundColor Green
Write-Host 'Business data      : NOT READ / NOT WRITTEN' -ForegroundColor Green
Write-Host 'Sales-order action : NOT CALLED' -ForegroundColor Green
Write-Host 'Production         : HARD BLOCKED BY REV3' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

if ($actualBlob -ne $ExpectedRev3Blob) {
    throw "REV3 blob mismatch. Refusing to patch or execute an unexpected script."
}

$source = [System.IO.File]::ReadAllText($Rev3Path, [System.Text.Encoding]::UTF8)
$old = '[Parameter(Mandatory)][System.Collections.Generic.List[object]]$Destination,'
$new = '[Parameter(Mandatory)][AllowEmptyCollection()][System.Collections.Generic.List[object]]$Destination,'

$occurrences = ([regex]::Matches($source, [regex]::Escape($old))).Count
if ($occurrences -ne 1) {
    throw "Expected exactly one REV3 Destination declaration to patch; found $occurrences."
}

$patched = $source.Replace($old, $new)
if ($patched -eq $source) {
    throw 'REV4 patch did not change REV3 source.'
}

$tempScript = Join-Path ([System.IO.Path]::GetTempPath()) ("GPIOrderIntake-BoyerSymbols-REV4-" + [Guid]::NewGuid().ToString('N') + '.ps1')

try {
    [System.IO.File]::WriteAllText($tempScript, $patched, [System.Text.UTF8Encoding]::new($false))

    Write-Host ''
    Write-Host 'REV3 blob verification: PASS' -ForegroundColor Green
    Write-Host 'REV4 narrow patch     : PASS' -ForegroundColor Green
    Write-Host 'Executing patched NAVX-aware GET-only probe...' -ForegroundColor Cyan
    Write-Host ''

    & $tempScript
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        throw "Patched REV3 probe returned exit code $LASTEXITCODE."
    }
}
finally {
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'GPI ORDER INTAKE BOYER SYMBOL PACKAGE INSPECTION REV4: LOCAL PATCH WRAPPER COMPLETE' -ForegroundColor Green
