#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# RESUME-ONLY wrapper over the proven installed-app authority tester.
# The prior publish run already reported deployment Completed.
# This wrapper contains no extension upload/install operation: it waits for installed 0.1.0.7 visibility,
# then uses the existing exact AITEST create/read/mandatory-cleanup harness.
# =====================================================================================================================
$ExpectedBaseBlob = '3e7b89f63dd058ab9c402980554b5bc62def144d'
$BasePath = 'scripts/Test-GPIOrderIntakeALAuthority-PRE.ps1'
$TargetVersion = '0.1.0.7'
$ExpectedPackageHash = '3B4AAA38CDB3937E046CC5A0E10CA60BBAF87CA1ABCF72BCB86F4CA7FC710C63'
$EnableFlag = 'GPI_ORDER_INTAKE_RESOLVER_RESUME_TEST_ENABLED'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PackagePath = Join-Path $RepoRoot 'order-intake-bc\.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.7.app'

Push-Location $RepoRoot
try {
    $headBlob = (& git rev-parse "HEAD:$BasePath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($headBlob)) {
        throw "Could not resolve committed base tester at HEAD:$BasePath"
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.7 - RESUME-ONLY INSTALLED RESOLVER TEST / PRE ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Expected base blob   : $ExpectedBaseBlob"
    Write-Host "HEAD base blob       : $headBlob"
    if ($headBlob -ne $ExpectedBaseBlob) { throw 'Committed no-publish authority tester changed. Review required.' }
    Write-Host 'Committed tester     : PASS' -ForegroundColor Green
    Write-Host "Target version       : $TargetVersion"
    Write-Host "Expected package SHA : $ExpectedPackageHash"
    Write-Host 'Target environment   : PRE_GAMERDOCS_CUTOVER_20260831 / sandbox'
    Write-Host 'Target company       : Gamer Packaging'
    Write-Host 'Controlled case      : GIOVANN / C-503003-12033922 / 56.42 M / Location 00'
    Write-Host 'Required read-back   : Unit Price 277.99'
    Write-Host 'Publish / install    : NONE - RESUME ONLY' -ForegroundColor Green
    Write-Host 'Cleanup              : MANDATORY exact AITEST Open/Draft only'
    Write-Host 'Release/Ship/Post    : NOT IMPLEMENTED / BLOCKED'
    Write-Host 'Production           : HARD BLOCKED'
    Write-Host ('=' * 120) -ForegroundColor Cyan

    if (-not (Test-Path -LiteralPath $PackagePath)) {
        throw "Local compiled 0.1.0.7 package is missing: $PackagePath"
    }
    $actualPackageHash = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash
    if ($actualPackageHash -ne $ExpectedPackageHash) {
        throw "Local compiled package SHA changed. Expected $ExpectedPackageHash; got $actualPackageHash. No BC action attempted."
    }
    Write-Host 'Local package SHA     : PASS (verification only; package will NOT be uploaded)' -ForegroundColor Green

    $base = (& git show "HEAD:$BasePath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($base)) { throw 'Committed base tester content was empty.' }

    $patched = $base

    $patches = @(
        [pscustomobject]@{
            Name = 'expected app version'
            Old = '$ExpectedAppVersion = ''0.1.0.0'''
            New = '$ExpectedAppVersion = ''0.1.0.7'''
            Count = 1
        },
        [pscustomobject]@{
            Name = 'enable flag'
            Old = 'GPI_ORDER_INTAKE_AL_AUTHORITY_TEST_ENABLED'
            New = $EnableFlag
            Count = 1
        },
        [pscustomobject]@{
            Name = 'installed revision'
            Old = '[int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 0 -and'
            New = '[int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 7 -and'
            Count = 1
        }
    )

    foreach ($patch in $patches) {
        $count = ([regex]::Matches($patched, [regex]::Escape([string]$patch.Old))).Count
        Write-Host ("Patch target {0,-24}: {1} / {2}" -f $patch.Name, $count, $patch.Count)
        if ($count -ne [int]$patch.Count) {
            throw "Expected exactly $($patch.Count) $($patch.Name) patch target(s); found $count."
        }
        $patched = $patched.Replace([string]$patch.Old, [string]$patch.New)
    }

    # Insert a visibility poll immediately before the base tester's existing exact installed-app check.
    # The existing check remains intact and runs after this poll.
    $installMarker = '# Verify exact app is already installed. This script does not upload or install anything.'
    $markerCount = ([regex]::Matches($patched, [regex]::Escape($installMarker))).Count
    Write-Host "Patch target visibility marker : $markerCount / 1"
    if ($markerCount -ne 1) { throw "Expected exactly one installed-app marker; found $markerCount." }

    $visibilityBlock = @'
# Resume-only visibility poll. Prior deployment already reported Completed.
$visibleGpi = @()
$installedVisible = @()
for ($visibilityAttempt = 1; $visibilityAttempt -le 60; $visibilityAttempt++) {
    $visibilityExtensions = Invoke-BcGet -Uri "$automationRoot/extensions?`$top=500" -Headers $script:Headers
    $visibleGpi = @($visibilityExtensions.value | Where-Object {
        [string]$_.id -eq $ExpectedAppId -or
        ([string]$_.displayName -eq $ExpectedAppName -and [string]$_.publisher -eq $ExpectedPublisher)
    })
    $installedVisible = @($visibleGpi | Where-Object {
        [string]$_.id -eq $ExpectedAppId -and
        [string]$_.displayName -eq $ExpectedAppName -and
        [string]$_.publisher -eq $ExpectedPublisher -and
        [int]$_.versionMajor -eq 0 -and [int]$_.versionMinor -eq 1 -and
        [int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 7 -and
        $_.isInstalled -eq $true
    })

    if ($installedVisible.Count -eq 1) { break }
    if ($installedVisible.Count -gt 1) { throw 'More than one exact installed GPI Order Intake 0.1.0.7 record is visible.' }

    if ($visibilityAttempt -eq 1 -or ($visibilityAttempt % 10) -eq 0) {
        Write-Host "Waiting for installed 0.1.0.7 visibility (attempt $visibilityAttempt/60)..." -ForegroundColor Yellow
        if ($visibleGpi.Count -gt 0) {
            @($visibleGpi | ForEach-Object {
                [pscustomobject][ordered]@{
                    id = [string]$_.id
                    displayName = [string]$_.displayName
                    publisher = [string]$_.publisher
                    version = "$($_.versionMajor).$($_.versionMinor).$($_.versionBuild).$($_.versionRevision)"
                    isInstalled = [bool]$_.isInstalled
                }
            }) | Format-Table -AutoSize | Out-Host
        }
    }
    Start-Sleep -Seconds 2
}

if ($installedVisible.Count -ne 1) {
    $visibleSummary = @($visibleGpi | ForEach-Object {
        [pscustomobject][ordered]@{
            id = [string]$_.id
            displayName = [string]$_.displayName
            publisher = [string]$_.publisher
            version = "$($_.versionMajor).$($_.versionMinor).$($_.versionBuild).$($_.versionRevision)"
            isInstalled = [bool]$_.isInstalled
        }
    })

    [ordered]@{
        success = $false
        result = 'DEPLOYMENT_COMPLETED_BUT_0_1_0_7_NOT_VISIBLE_AS_INSTALLED'
        expectedVersion = $ExpectedAppVersion
        visibleGpiRecords = $visibleSummary
        safety = [ordered]@{
            publishThisRun = 'NONE'
            businessDataWrites = 'NONE'
            salesOrderAction = 'NOT CALLED'
            production = 'HARD BLOCKED'
        }
    } | ConvertTo-Json -Depth 10

    throw "Expected installed $ExpectedAppName $ExpectedAppVersion never became visible. No republish attempted and no Sales Order action was called."
}
Write-Host 'PRE installed 0.1.0.7 visibility: PASS' -ForegroundColor Green

'@

    $patched = $patched.Replace($installMarker, $visibilityBlock + $installMarker)

    # Strengthen the existing successful final line so the round trip only passes when the observed price matched 277.99.
    $finalMarker = "Write-Host 'GPI ORDER INTAKE AL AUTHORITY ROUND-TRIP: PASS' -ForegroundColor Green"
    $finalCount = ([regex]::Matches($patched, [regex]::Escape($finalMarker))).Count
    Write-Host "Patch target final PASS        : $finalCount / 1"
    if ($finalCount -ne 1) { throw "Expected exactly one final PASS marker; found $finalCount." }

    $finalReplacement = @'
if ($testResult.pricingResult -ne 'MATCHED_HISTORICAL_LOCATION_PRICE') {
        throw "Resolver test cleaned up safely but Unit Price did not match required exact-context price 277.99. Observed: $($testResult.observedUnitPrice)"
    }
    Write-Host 'Resolver exact-price assertion: PASS (277.99)' -ForegroundColor Green
    Write-Host 'GPI ORDER INTAKE 0.1.0.7 RESOLVER RESUME ROUND-TRIP: PASS' -ForegroundColor Green
'@.TrimEnd("`r","`n")
    $patched = $patched.Replace($finalMarker, $finalReplacement)

    if ($patched -match "ExpectedAppVersion\s*=\s*'0\.1\.0\.0'") { throw 'Old expected app version remains.' }
    if ($patched -match 'versionRevision\s+-eq\s+0') { throw 'Old installed revision check remains.' }
    if ($patched -match 'GPI_ORDER_INTAKE_AL_AUTHORITY_TEST_ENABLED') { throw 'Old enable flag remains.' }
    if ($patched -match '(?i)extensionUpload|extensionContent|Microsoft\.NAV\.upload') {
        throw 'Resume tester unexpectedly contains extension upload/install operations.'
    }

    $tempScript = Join-Path $PSScriptRoot ('.GPIOrderIntake-ResolverResume-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $tempScript -Value $patched -Encoding UTF8 -NoNewline
        Write-Host 'Resume-only tester patch: PASS' -ForegroundColor Green
        Write-Host ''

        $previous = [Environment]::GetEnvironmentVariable($EnableFlag)
        [Environment]::SetEnvironmentVariable($EnableFlag, 'true')
        try {
            & $tempScript
            if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
                throw "Resolver resume tester exited with code $LASTEXITCODE."
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
