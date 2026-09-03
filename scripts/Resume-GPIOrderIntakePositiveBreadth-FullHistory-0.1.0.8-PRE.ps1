#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# PRE-ONLY / ALREADY-INSTALLED 0.1.0.8 / ONE REMAINING POSITIVE BREADTH CASE
#
# The prior breadth run already passed Pizza/00 and Salsa16/00 before reaching Vinegar/082.
# Vinegar/082 was then diagnosed separately and proved 49.742 M @ 212.60 with cleanup PASS.
# Full-history GET evidence independently confirmed latest-two 212.60/212.60 for Vinegar/082.
# Therefore only the unexecuted Salsa24/082 breadth case is run here.
#
# No extension upload/install. One exact AITEST Draft maximum. Mandatory cleanup.
# =====================================================================================================================
$ExpectedBaseBlob = '3e7b89f63dd058ab9c402980554b5bc62def144d'
$BasePath = 'scripts/Test-GPIOrderIntakeALAuthority-PRE.ps1'
$ExpectedPackageHash = '6C8E9AA69685622073294B21B54F92032887DDE66D49018075D88E624D22389A'
$EnableFlag = 'GPI_ORDER_INTAKE_POSITIVE_BREADTH_RESUME_018_ENABLED'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PackagePath = Join-Path $RepoRoot 'order-intake-bc\.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.8.app'

function Replace-ExactOnce {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Name
    )
    $count = ([regex]::Matches($Text, [regex]::Escape($Old))).Count
    Write-Host ("Patch target {0,-28}: {1} / 1" -f $Name, $count)
    if ($count -ne 1) { throw "Expected exactly one $Name patch target; found $count." }
    return $Text.Replace($Old, $New)
}

Push-Location $RepoRoot
try {
    $headBlob = (& git rev-parse "HEAD:$BasePath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($headBlob)) {
        throw "Could not resolve committed base tester at HEAD:$BasePath"
    }
    if ($headBlob -ne $ExpectedBaseBlob) {
        throw "Committed no-publish authority tester changed. Expected $ExpectedBaseBlob; got $headBlob."
    }

    if (-not (Test-Path -LiteralPath $PackagePath)) { throw "Compiled package missing: $PackagePath" }
    $actualHash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash
    if ($actualHash -ne $ExpectedPackageHash) {
        throw "Compiled package SHA changed. Expected $ExpectedPackageHash; got $actualHash."
    }

    $base = (& git show "HEAD:$BasePath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($base)) { throw 'Committed base tester content was empty.' }

    $test = $base
    $test = Replace-ExactOnce $test '$ExpectedAppVersion = ''0.1.0.0''' '$ExpectedAppVersion = ''0.1.0.8''' 'expected app version'
    $test = Replace-ExactOnce $test 'GPI_ORDER_INTAKE_AL_AUTHORITY_TEST_ENABLED' $EnableFlag 'enable flag'
    $test = Replace-ExactOnce $test '[int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 0 -and' '[int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 8 -and' 'installed revision'
    $test = Replace-ExactOnce $test '$Quantity            = [decimal]56.42' '$Quantity            = [decimal]33.852' 'quantity'
    $test = Replace-ExactOnce $test '$LocationCode        = ''00''' '$LocationCode        = ''082''' 'location'
    $test = Replace-ExactOnce $test '$ExpectedLocationId  = ''53ec399a-c4e1-eb11-abff-7c05070e4047''' '$ExpectedLocationId  = ''8cec399a-c4e1-eb11-abff-7c05070e4047''' 'location ID'
    $test = Replace-ExactOnce $test '$HistoricalUnitPrice = [decimal]277.99' '$HistoricalUnitPrice = [decimal]289.49' 'full-history price'
    $test = Replace-ExactOnce $test '$TestPrefix          = ''AITEST-ALAUTH-''' '$TestPrefix          = ''AITEST-BR8-S24-''' 'test prefix'

    $oldFinalPass = "Write-Host 'GPI ORDER INTAKE AL AUTHORITY ROUND-TRIP: PASS' -ForegroundColor Green"
    $newFinalPass = @'
if ($pricingResult -ne 'MATCHED_HISTORICAL_LOCATION_PRICE') {
    throw 'SALSA24_082_VARIABLE_QTY: cleaned up safely but context price did not equal 289.49.'
}
Write-Host 'SALSA24_082_VARIABLE_QTY: EXACT QUANTITY + CONTEXT PRICE + CLEANUP PASS' -ForegroundColor Green
Write-Host 'GPI ORDER INTAKE 0.1.0.8 POSITIVE BREADTH RESUME: PASS' -ForegroundColor Green
'@.TrimEnd("`r","`n")
    $test = Replace-ExactOnce $test $oldFinalPass $newFinalPass 'final PASS'

    if ($test -match '(?i)extensionUpload|extensionContent|Microsoft\.NAV\.upload') {
        throw 'Resume tester unexpectedly contains extension upload/install operations.'
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 - POSITIVE BREADTH RESUME / PRE ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed base blob : $headBlob"
    Write-Host "Local package SHA   : $actualHash (verification only)"
    Write-Host 'Installed app       : GPI Order Intake 0.1.0.8'
    Write-Host 'Prior completed     : Pizza/00; Salsa16/00; Vinegar/082 diagnostic @ 212.60'
    Write-Host 'Remaining case      : GIOVANN / C-503003-12033922 / 33.852 M / Location 082'
    Write-Host 'Full-history price  : 289.49 / latest two agree'
    Write-Host 'Pricing key         : customer + item + UOM + location; quantity excluded'
    Write-Host 'Publish / install   : NONE' -ForegroundColor Green
    Write-Host 'Cleanup             : MANDATORY exact AITEST Open/Draft only'
    Write-Host 'Release/Ship/Post   : NOT IMPLEMENTED / BLOCKED'
    Write-Host 'Production          : HARD BLOCKED'
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $temp = Join-Path $PSScriptRoot ('.GPIOrderIntake-BreadthResume018-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    $previousEnable = [Environment]::GetEnvironmentVariable($EnableFlag)
    [Environment]::SetEnvironmentVariable($EnableFlag, 'true')
    try {
        Set-Content -LiteralPath $temp -Value $test -Encoding UTF8 -NoNewline
        & $temp
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "Positive breadth resume tester exited with code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        if ($null -eq $previousEnable) {
            Remove-Item "Env:$EnableFlag" -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable($EnableFlag, $previousEnable)
        }
    }
}
finally {
    Pop-Location
}
