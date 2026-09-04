#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $RepoRoot
try {
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE - CUSTOMER PDF PARSER OFFLINE REGRESSION' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'Corpus families        : Berner scanned/image PDF; Herdez Coupa digital PDF'
    Write-Host 'PDF extraction         : transport only; deterministic customer parser owns interpretation'
    Write-Host 'Source price           : evidence only; never BC pricing authority'
    Write-Host 'Business Central calls : NONE' -ForegroundColor Green
    Write-Host 'Extension mutation     : NONE' -ForegroundColor Green
    Write-Host 'Business data writes   : NONE' -ForegroundColor Green
    Write-Host 'Production             : NOT CONTACTED' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $python) {
        $python = Get-Command py -ErrorAction SilentlyContinue
    }
    if ($null -eq $python) { throw 'Python interpreter not found in PATH.' }

    & $python.Source -m pytest backend/tests/test_order_intake_customer_pdf.py -q
    if ($LASTEXITCODE -ne 0) {
        throw "Customer PDF parser regression failed with exit code $LASTEXITCODE."
    }

    Write-Host ''
    Write-Host 'GPI ORDER INTAKE CUSTOMER PDF PARSER REGRESSION: PASS' -ForegroundColor Green
}
finally {
    Pop-Location
}
