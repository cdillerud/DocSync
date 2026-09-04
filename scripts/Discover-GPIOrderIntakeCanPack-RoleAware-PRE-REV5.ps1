#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$BasePath = Join-Path $PSScriptRoot 'Discover-GPIOrderIntakeCanPack-RoleAware-PRE-REV4.ps1'
$ExpectedBaseBlob = '55f586da333ec96b2078d0469d73523392486afb'

if (-not (Test-Path -LiteralPath $BasePath -PathType Leaf)) {
    throw "Committed REV4 base script not found: $BasePath"
}

$actualBlob = (& git hash-object -- $BasePath).Trim()
if ($LASTEXITCODE -ne 0) { throw 'git hash-object failed while validating REV4 base script.' }
if ($actualBlob -ne $ExpectedBaseBlob) {
    throw "Unexpected REV4 base blob: $actualBlob"
}

$source = Get-Content -LiteralPath $BasePath -Raw

$old = @'
$candidateItemNos = @(
    @($directItemMatches | ForEach-Object {[string]$_.itemNumber}) +
    @($historyLikely | ForEach-Object {[string]$_.itemNumber})
) | Where-Object {-not [string]::IsNullOrWhiteSpace($_)} | Sort-Object -Unique
'@

$new = @'
$candidateItemNos = @(
    @(
        @($directItemMatches | ForEach-Object {[string]$_.itemNumber}) +
        @($historyLikely | ForEach-Object {[string]$_.itemNumber})
    ) | Where-Object {-not [string]::IsNullOrWhiteSpace($_)} | Sort-Object -Unique
)
'@

$anchorCount = ([regex]::Matches($source, [regex]::Escape($old))).Count
Write-Host "Patch target single-candidate array : $anchorCount / 1"
if ($anchorCount -ne 1) {
    throw "Expected one single-candidate array patch target; found $anchorCount."
}

$source = $source.Replace($old, $new)
$titleOld = "GPI ORDER INTAKE - CANPACK ROLE-AWARE DISCOVERY REV4 / PRE GET ONLY"
$titleNew = "GPI ORDER INTAKE - CANPACK ROLE-AWARE DISCOVERY REV5 / PRE GET ONLY"
$titleCount = ([regex]::Matches($source, [regex]::Escape($titleOld))).Count
Write-Host "Patch target REV5 title              : $titleCount / 1"
if ($titleCount -ne 1) {
    throw "Expected one REV4 title patch target; found $titleCount."
}
$source = $source.Replace($titleOld, $titleNew)

$tempPath = Join-Path $PSScriptRoot ('.GPIOrderIntake-CanPack-REV5-{0}.tmp.ps1' -f ([guid]::NewGuid().ToString('N')))

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - CANPACK ROLE-AWARE DISCOVERY REV5 / SINGLE-CANDIDATE ARRAY FIX' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Committed REV4 blob : $ExpectedBaseBlob"
Write-Host 'Correction           : force candidateItemNos to remain an array when exactly one candidate resolves'
Write-Host 'Business logic       : UNCHANGED from committed REV4'
Write-Host 'HTTP methods         : GET ONLY'
Write-Host 'Extension mutation   : NONE'
Write-Host 'Business data write  : NONE'
Write-Host 'Sales-order action   : NOT CALLED'
Write-Host 'Production           : HARD BLOCKED'
Write-Host ('=' * 120) -ForegroundColor Cyan

try {
    Set-Content -LiteralPath $tempPath -Value $source -Encoding utf8NoBOM
    & $tempPath
    if (-not $?) { throw 'Temporary REV5 discovery script failed.' }
}
finally {
    Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
}
