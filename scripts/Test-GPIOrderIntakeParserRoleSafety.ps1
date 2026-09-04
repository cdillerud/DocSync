#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $RepoRoot
try {
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE - OFFLINE PARSER ROLE-SAFETY REGRESSION' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'Business Central calls : NONE' -ForegroundColor Green
    Write-Host 'Extension mutation     : NONE' -ForegroundColor Green
    Write-Host 'Business data writes   : NONE' -ForegroundColor Green
    Write-Host 'Production             : NOT CONTACTED' -ForegroundColor Green
    Write-Host 'Test target            : backend/tests/test_order_intake_parsers.py'
    Write-Host 'Required CanPack rule  : supplier source values preserved; BC Sales Order values unresolved'
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $python) {
        $python = Get-Command py -ErrorAction SilentlyContinue
    }
    if ($null -eq $python) { throw 'Python interpreter not found in PATH.' }

    & $python.Source -m pytest backend/tests/test_order_intake_parsers.py -q
    if ($LASTEXITCODE -ne 0) { throw "Parser regression failed with exit code $LASTEXITCODE." }

    Write-Host ''
    Write-Host 'GPI ORDER INTAKE PARSER ROLE-SAFETY REGRESSION: PASS' -ForegroundColor Green
}
finally {
    Pop-Location
}
