#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Rev2 = Join-Path $PSScriptRoot 'Invoke-GPIHub-V107-REV2-Warehouse-Canonical-Shipment-Resume.ps1'
if (-not (Test-Path -LiteralPath $Rev2 -PathType Leaf)) {
    throw "V107 REV2 resume script was not materialized: $Rev2"
}

Write-Host 'V107_REV2_RESUME_WRAPPER=PASS' -ForegroundColor Cyan
& $Rev2
