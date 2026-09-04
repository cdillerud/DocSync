#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$OfflinePath   = Join-Path $PSScriptRoot 'Test-GPIOrderIntakeCustomerPdfParsers.ps1'
$DiscoveryPath = Join-Path $PSScriptRoot 'Discover-GPIOrderIntakeCustomerPdfMappings-PRE.ps1'

$ExpectedOfflineBlob   = 'a045d1c135a7e13157ff1ab9f7ce0cbb688b6ced'
$ExpectedDiscoveryBlob = '3fbc8ca3ea8f9a5dfe0feeff00030594ad5eb451'

foreach ($entry in @(
    [pscustomobject]@{Label='offline parser gate';Path=$OfflinePath;Expected=$ExpectedOfflineBlob},
    [pscustomobject]@{Label='GET-only PRE discovery';Path=$DiscoveryPath;Expected=$ExpectedDiscoveryBlob}
)) {
    if (-not (Test-Path -LiteralPath $entry.Path -PathType Leaf)) {
        throw "Committed $($entry.Label) script not found: $($entry.Path)"
    }
    $actual = (& git hash-object -- $entry.Path).Trim()
    if ($LASTEXITCODE -ne 0) { throw "git hash-object failed for $($entry.Path)." }
    if ($actual -ne $entry.Expected) {
        throw "Unexpected $($entry.Label) blob: $actual"
    }
}

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - CUSTOMER PDF MAPPING GATE / OFFLINE THEN PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Offline gate blob     : $ExpectedOfflineBlob"
Write-Host "Discovery gate blob   : $ExpectedDiscoveryBlob"
Write-Host 'Stage 1               : corrected customer-PDF parser regression; NO BC contact'
Write-Host 'Stage 2               : exact PRE sandbox/company discovery; GET ONLY'
Write-Host 'Extension mutation    : NONE' -ForegroundColor Green
Write-Host 'Business data write   : NONE' -ForegroundColor Green
Write-Host 'Sales-order action    : NOT CALLED' -ForegroundColor Green
Write-Host 'Production            : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

Write-Host ''
Write-Host 'STAGE 1 - OFFLINE CUSTOMER PDF REGRESSION' -ForegroundColor Cyan
& $OfflinePath
if (-not $?) { throw 'Offline customer PDF regression did not complete successfully.' }

Write-Host ''
Write-Host 'STAGE 1 PASS - proceeding to GET-only PRE discovery.' -ForegroundColor Green
Write-Host ''
Write-Host 'STAGE 2 - PRE CUSTOMER/ITEM/UOM/HISTORY DISCOVERY' -ForegroundColor Cyan
& $DiscoveryPath
if (-not $?) { throw 'GET-only PRE discovery did not complete successfully.' }

Write-Host ''
Write-Host 'GPI ORDER INTAKE CUSTOMER PDF MAPPING GATE: PASS' -ForegroundColor Green
