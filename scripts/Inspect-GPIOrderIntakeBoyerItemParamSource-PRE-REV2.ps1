#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedSourceBlob = 'a517ab02873e8447591f8424dc0dfadad909fbaa'
$SourceScript = Join-Path $PSScriptRoot 'Inspect-GPIOrderIntakeBoyerItemParamSource-PRE.ps1'

if (-not (Test-Path -LiteralPath $SourceScript)) {
    throw "Source probe not found: $SourceScript"
}

$ActualSourceBlob = (& git hash-object -- $SourceScript).Trim()

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - BOYER ITEM PARAMETER SOURCE TRACE REV2 / LOCAL PARSER REPAIR' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Expected source blob : $ExpectedSourceBlob"
Write-Host "Actual source blob   : $ActualSourceBlob"

if ($ActualSourceBlob -ne $ExpectedSourceBlob) {
    throw 'Source probe blob verification failed. Refusing to patch or run.'
}

Write-Host 'Source blob verification: PASS' -ForegroundColor Green
Write-Host 'Patch scope             : table declaration regex construction only'
Write-Host 'BC mutation             : NONE'
Write-Host 'Sales-order action      : NOT CALLED'
Write-Host ('=' * 120) -ForegroundColor Cyan

$raw = Get-Content -LiteralPath $SourceScript -Raw
$old = '                    if ($line -match "(?i)^\s*table\s+(\d+)\s+\"?$escaped\"?\s*$") {'
$new = @'
                    $tablePattern = '(?i)^\s*table\s+(\d+)\s+"?' + $escaped + '"?\s*$'
                    if ($line -match $tablePattern) {
'@

$matches = ([regex]::Matches($raw, [regex]::Escape($old))).Count
if ($matches -ne 1) {
    throw "Expected exactly one parser target; found $matches."
}

$patched = $raw.Replace($old, $new.TrimEnd("`r", "`n"))
$tempScript = Join-Path ([System.IO.Path]::GetTempPath()) ("GPIOrderIntake-BoyerItemParam-REV2-" + [Guid]::NewGuid().ToString('N') + '.ps1')

try {
    Set-Content -LiteralPath $tempScript -Value $patched -Encoding UTF8 -NoNewline

    $patchedRaw = Get-Content -LiteralPath $tempScript -Raw
    if ($patchedRaw -notmatch [regex]::Escape("`$tablePattern = '(?i)^\s*table\s+(\d+)\s+\"?' + `$escaped + '\"?\s*`$'")) {
        throw 'REV2 parser patch verification failed.'
    }

    Write-Host 'REV2 narrow patch       : PASS' -ForegroundColor Green
    Write-Host 'Starting patched GET-only ItemParam source trace...' -ForegroundColor Cyan
    Write-Host ''

    & $tempScript
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        throw "Patched source probe exited with code $LASTEXITCODE."
    }
}
finally {
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'GPI ORDER INTAKE BOYER ITEM PARAMETER SOURCE TRACE REV2: LOCAL PATCH WRAPPER COMPLETE' -ForegroundColor Green
