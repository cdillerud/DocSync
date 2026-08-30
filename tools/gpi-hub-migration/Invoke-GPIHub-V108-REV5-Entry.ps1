#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Write-Host 'V108_REV6_DELEGATE_FROM_REV5=PASS' -ForegroundColor Cyan
$Rev6 = Join-Path $PSScriptRoot 'Invoke-GPIHub-V108-REV6-Entry.ps1'
if (-not (Test-Path -LiteralPath $Rev6 -PathType Leaf)) { throw "V108 REV6 entry missing: $Rev6" }
& $Rev6
