#requires -Version 7.0
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Write-Host 'V108_REV8_DELEGATE_FROM_REV7=PASS' -ForegroundColor Cyan
$Rev8 = Join-Path $PSScriptRoot 'Invoke-GPIHub-V108-REV8-Health-Resume-Corpus.ps1'
if (-not (Test-Path -LiteralPath $Rev8 -PathType Leaf)) { throw "V108 REV8 entry missing: $Rev8" }
& $Rev8
