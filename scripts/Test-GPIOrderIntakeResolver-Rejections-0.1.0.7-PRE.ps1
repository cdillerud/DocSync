#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host ('=' * 120) -ForegroundColor Yellow
Write-Host 'GPI ORDER INTAKE 0.1.0.7 FIXED-QUANTITY REJECTION GATE: SUPERSEDED' -ForegroundColor Yellow
Write-Host ('=' * 120) -ForegroundColor Yellow
Write-Host 'This historical test is intentionally disabled.'
Write-Host 'Reason: a PO quantity that differs from the first fixture is not inherently invalid.'
Write-Host 'Current architecture: the incoming PO owns quantity; BC validates item/UOM/quantity structure; pricing evidence is resolved independently.'
Write-Host 'Use the 0.1.0.8 variable-quantity resolver gates instead.'
Write-Host 'BC contacted       : NO' -ForegroundColor Green
Write-Host 'Business-data write: NONE' -ForegroundColor Green
Write-Host 'Production         : NO' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Yellow

throw 'SUPERSEDED TEST BLOCKED: fixed-quantity negative testing is not valid for the variable-PO Order Intake architecture.'
