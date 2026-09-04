#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY WRAPPER OVER THE PROVEN AL PUBLISH/TEST HARNESS
# Publishes only the exact compiled GPI Order Intake 0.1.0.7 package SHA, then executes one tagged Giovanni resolver
# round trip and requires 56.42 M @ 277.99 / Location 00 before mandatory cleanup can be considered a PASS.
# The pristine base harness is read from HEAD, never from a potentially modified working-tree copy.
# =====================================================================================================================
$ExpectedBaseBlob = '5583c0ad8f6a1ae8cf6f49466ab818b849bf0d16'
$BasePath = 'scripts/Publish-Test-GPIOrderIntakeAL-PRE.ps1'
$ExpectedPackageHash = '3B4AAA38CDB3937E046CC5A0E10CA60BBAF87CA1ABCF72BCB86F4CA7FC710C63'
$TargetVersion = '0.1.0.7'
$EnableFlag = 'GPI_ORDER_INTAKE_RESOLVER_PRE_TEST_ENABLED'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Push-Location $RepoRoot
try {
    $headBlob = (& git rev-parse "HEAD:$BasePath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($headBlob)) {
        throw "Could not resolve committed base harness at HEAD:$BasePath"
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.7 - RESOLVER PUBLISH + EXACT-PRICE ROUND TRIP / PRE ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Expected base blob   : $ExpectedBaseBlob"
    Write-Host "HEAD base blob       : $headBlob"
    if ($headBlob -ne $ExpectedBaseBlob) { throw 'Committed base publish/test harness blob changed. Review required.' }
    Write-Host 'Committed harness    : PASS' -ForegroundColor Green
    Write-Host "Target version       : $TargetVersion"
    Write-Host "Expected package SHA : $ExpectedPackageHash"
    Write-Host 'Target environment   : PRE_GAMERDOCS_CUTOVER_20260831 / sandbox'
    Write-Host 'Target company       : Gamer Packaging'
    Write-Host 'Controlled case      : GIOVANN / C-503003-12033922 / 56.42 M / Location 00'
    Write-Host 'Required read-back   : Unit Price 277.99'
    Write-Host 'Cleanup              : MANDATORY exact AITEST Open/Draft only'
    Write-Host 'Release/Ship/Post    : NOT IMPLEMENTED / BLOCKED'
    Write-Host 'Production           : HARD BLOCKED'
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $base = (& git show "HEAD:$BasePath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($base)) { throw 'Committed base harness content was empty.' }

    $patches = @(
        [pscustomobject]@{ Name='version'; Old='0.1.0.0'; New=$TargetVersion; ExpectedCount=4 },
        [pscustomobject]@{ Name='package SHA'; Old='D92A5D2F724F258A690ED0F4E54219A6FE4C9ABCFE3A7FCB731C21E33E266E44'; New=$ExpectedPackageHash; ExpectedCount=1 },
        [pscustomobject]@{ Name='enable flag'; Old='GPI_ORDER_INTAKE_AL_PRE_TEST_ENABLED'; New=$EnableFlag; ExpectedCount=1 }
    )

    $patched = $base
    foreach ($patch in $patches) {
        $count = ([regex]::Matches($patched, [regex]::Escape([string]$patch.Old))).Count
        Write-Host ("Patch target {0,-13}: {1} / {2}" -f $patch.Name, $count, $patch.ExpectedCount)
        if ($count -ne [int]$patch.ExpectedCount) {
            throw "Expected exactly $($patch.ExpectedCount) $($patch.Name) patch target(s); found $count."
        }
        $patched = $patched.Replace([string]$patch.Old, [string]$patch.New)
    }

    # Patch only the unique final PASS marker. This is intentionally newline-format agnostic.
    $oldFinalPass = "Write-Host 'GPI ORDER INTAKE AL AUTHORITY ROUND-TRIP: PASS' -ForegroundColor Green"
    $newFinalPass = @'
if ($pricingResult -ne 'MATCHED_HISTORICAL_LOCATION_PRICE') {
    throw "Resolver round trip cleaned up safely but returned Unit Price $observedPrice instead of required 277.99."
}
Write-Host 'Resolver exact-price assertion: PASS (277.99)' -ForegroundColor Green
Write-Host 'GPI ORDER INTAKE 0.1.0.7 RESOLVER ROUND-TRIP: PASS' -ForegroundColor Green
'@.TrimEnd("`r","`n")

    $finalCount = ([regex]::Matches($patched, [regex]::Escape($oldFinalPass))).Count
    Write-Host "Patch target final PASS    : $finalCount / 1"
    if ($finalCount -ne 1) { throw "Expected exactly one final PASS patch target; found $finalCount." }
    $patched = $patched.Replace($oldFinalPass, $newFinalPass)

    if ($patched -match '0\.1\.0\.0') { throw 'Old app version marker remains after patching.' }
    if ($patched -match 'D92A5D2F724F258A690ED0F4E54219A6FE4C9ABCFE3A7FCB731C21E33E266E44') { throw 'Old package SHA remains after patching.' }
    if ($patched -match 'GPI_ORDER_INTAKE_AL_PRE_TEST_ENABLED') { throw 'Old enable flag remains after patching.' }
    if ($patched.IndexOf('MATCHED_HISTORICAL_LOCATION_PRICE', [StringComparison]::Ordinal) -lt 0) { throw 'Exact historical-price assertion marker missing.' }
    if ($patched.IndexOf('Resolver exact-price assertion: PASS (277.99)', [StringComparison]::Ordinal) -lt 0) { throw 'Resolver exact-price final assertion missing.' }

    $tempScript = Join-Path $PSScriptRoot ('.GPIOrderIntake-ResolverPublishTest-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $tempScript -Value $patched -Encoding UTF8 -NoNewline
        Write-Host 'Resolver harness patch : PASS' -ForegroundColor Green
        Write-Host ''

        $previous = [Environment]::GetEnvironmentVariable($EnableFlag)
        [Environment]::SetEnvironmentVariable($EnableFlag, 'true')
        try {
            & $tempScript
            if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
                throw "Resolver publish/test harness exited with code $LASTEXITCODE."
            }
        }
        finally {
            if ($null -eq $previous) {
                Remove-Item "Env:$EnableFlag" -ErrorAction SilentlyContinue
            }
            else {
                [Environment]::SetEnvironmentVariable($EnableFlag, $previous)
            }
        }
    }
    finally {
        Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
