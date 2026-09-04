#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedRev2Blob = '907a0a06a0d2d495548b7de84bb0d5b630ca93c8'
$Rev2Script = Join-Path $PSScriptRoot 'Publish-Read-GPIOrderIntakeOrderCreationVsBoyer-PRE-REV2.ps1'

if (-not (Test-Path -LiteralPath $Rev2Script)) { throw "REV2 diagnostic wrapper not found: $Rev2Script" }
$ActualRev2Blob = (& git hash-object -- $Rev2Script).Trim()

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - ORDER CREATION VS BOYER REV3 / REPO-ROOT-PRESERVING' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Expected REV2 blob : $ExpectedRev2Blob"
Write-Host "Actual REV2 blob   : $ActualRev2Blob"
if ($ActualRev2Blob -ne $ExpectedRev2Blob) { throw 'REV2 wrapper blob verification failed.' }
Write-Host 'REV2 blob verification : PASS' -ForegroundColor Green
Write-Host 'Patch scope            : TEMP SCRIPT LOCATION ONLY'
Write-Host 'Comparison scope       : Qty + UOM + Unit Price; Location reported separately'
Write-Host 'Business data writes   : NONE'
Write-Host 'Sales-order action     : NOT CALLED'
Write-Host 'Production             : HARD BLOCKED'
Write-Host ('=' * 120) -ForegroundColor Cyan

$raw = Get-Content -LiteralPath $Rev2Script -Raw
$old = '$tempScript = Join-Path ([IO.Path]::GetTempPath()) (''GPIOrderIntake-OrderCreationVsBoyer-REV2-'' + [guid]::NewGuid().ToString(''N'') + ''.ps1'')'
$new = '$tempScript = Join-Path $PSScriptRoot (''.GPIOrderIntake-OrderCreationVsBoyer-REV2-'' + [guid]::NewGuid().ToString(''N'') + ''.tmp.ps1'')'

$count = ([regex]::Matches($raw, [regex]::Escape($old))).Count
if ($count -ne 1) { throw "Expected exactly one REV2 temp-script location target; found $count." }
$patched = $raw.Replace($old, $new)

$tempWrapper = Join-Path $PSScriptRoot ('.GPIOrderIntake-OrderCreationVsBoyer-REV3-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
try {
    Set-Content -LiteralPath $tempWrapper -Value $patched -Encoding UTF8 -NoNewline
    Write-Host 'REV3 repo-root patch    : PASS' -ForegroundColor Green
    Write-Host 'Starting guarded diagnostic...' -ForegroundColor Cyan
    Write-Host ''
    & $tempWrapper
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "Patched REV2 wrapper exited with code $LASTEXITCODE." }
}
finally {
    Remove-Item -LiteralPath $tempWrapper -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'GPI ORDER INTAKE ORDER CREATION VS BOYER REV3: WRAPPER COMPLETE' -ForegroundColor Green
