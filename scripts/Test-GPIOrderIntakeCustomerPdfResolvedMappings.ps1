#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $RepoRoot
try {
    $targets = @(
        'backend/order_intake/models.py',
        'backend/order_intake/customer_pdf_mapping.py',
        'backend/order_intake/parsers/customer_pdf.py',
        'backend/tests/test_order_intake_customer_pdf.py'
    )

    foreach ($target in $targets) {
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
            throw "Required mapping regression source missing: $target"
        }
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE - CUSTOMER PDF RESOLVED MAPPING OFFLINE REGRESSION' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'Berner proof          : 811476 + 21579-858231 + exact 68,000 EA profile -> 21759-858231 / 72.2 M'
    Write-Host 'Berner quantity rule  : FAIL CLOSED if incoming quantity/UOM differs; historical 72.2 M is not a universal template'
    Write-Host 'Herdez proof          : 000000000004003467 -> 20113526 / M / Ship-to 001 / Location 00'
    Write-Host 'Herdez quantity rule  : incoming positive M quantity remains authoritative after proven THOUSAND-to-M semantics'
    Write-Host 'Duplicate policy      : exact existing customer PO -> DUPLICATE; never create a second order'
    Write-Host 'Source price policy   : evidence/corroboration only; Business Central remains pricing authority'
    Write-Host 'Business Central calls: NONE' -ForegroundColor Green
    Write-Host 'Extension mutation    : NONE' -ForegroundColor Green
    Write-Host 'Business data writes  : NONE' -ForegroundColor Green
    Write-Host 'Production            : NOT CONTACTED' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $python = Get-Command python -ErrorAction Stop

    & $python.Source -m py_compile @($targets | Where-Object { $_ -like '*.py' })
    if ($LASTEXITCODE -ne 0) { throw "Python compile gate failed with exit code $LASTEXITCODE." }
    Write-Host 'Python compile gate    : PASS' -ForegroundColor Green

    $backend = Join-Path $RepoRoot 'backend'
    $oldPythonPath = $env:PYTHONPATH
    try {
        if ([string]::IsNullOrWhiteSpace($oldPythonPath)) {
            $env:PYTHONPATH = $backend
        }
        else {
            $env:PYTHONPATH = "$backend$([IO.Path]::PathSeparator)$oldPythonPath"
        }

        & $python.Source -m pytest 'backend/tests/test_order_intake_customer_pdf.py' -q
        if ($LASTEXITCODE -ne 0) { throw "Customer PDF resolved-mapping pytest gate failed with exit code $LASTEXITCODE." }
    }
    finally {
        $env:PYTHONPATH = $oldPythonPath
    }

    Write-Host ''
    Write-Host 'GPI ORDER INTAKE CUSTOMER PDF RESOLVED MAPPING REGRESSION: PASS' -ForegroundColor Green
}
finally {
    Pop-Location
}
