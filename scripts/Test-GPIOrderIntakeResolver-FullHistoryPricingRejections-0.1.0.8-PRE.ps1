#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# PRE-ONLY / ALREADY-INSTALLED GPI ORDER INTAKE 0.1.0.8
# FULL-HISTORY PRICING-EVIDENCE REJECTION GATE
#
# These two fixtures were discovered only after removing the stale $top=500 profiler cap.
# No extension upload/install occurs here. Each case must reject before draft creation and leave zero AITEST residuals.
# =====================================================================================================================
$ExpectedBaseBlob = '3e7b89f63dd058ab9c402980554b5bc62def144d'
$BasePath = 'scripts/Test-GPIOrderIntakeALAuthority-PRE.ps1'
$TargetVersion = '0.1.0.8'
$ExpectedPackageHash = '6C8E9AA69685622073294B21B54F92032887DDE66D49018075D88E624D22389A'
$EnableFlag = 'GPI_ORDER_INTAKE_FULL_HISTORY_REJECTIONS_018_ENABLED'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PackagePath = Join-Path $RepoRoot 'order-intake-bc\.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.8.app'

# Quantity is intentionally not used as a pricing key. Any positive structurally valid M quantity can exercise these
# item/UOM/location pricing contexts. These cases target pricing evidence only.
$Cases = @(
    [pscustomobject][ordered]@{
        name = 'VINEGAR_001_LATEST_TWO_CONFLICT'
        itemNumber = 'C-8808-12026443'
        quantity = '49.742'
        uom = 'M'
        location = '001'
        expectedPattern = 'two most recent pricing-context posted invoices disagree on Unit Price'
        reason = 'Full-history GET profile: Vinegar / M / Location 001 has two observations whose latest two Unit Prices disagree.'
    },
    [pscustomobject][ordered]@{
        name = 'VINEGAR_002_ONE_OBSERVATION'
        itemNumber = 'C-8808-12026443'
        quantity = '49.742'
        uom = 'M'
        location = '002'
        expectedPattern = 'Only one posted invoice observation exists'
        reason = 'Full-history GET profile: Vinegar / M / Location 002 has exactly one posted invoice observation.'
    }
)

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

    $common = $base
    $common = Replace-ExactOnce $common '$ExpectedAppVersion = ''0.1.0.0''' '$ExpectedAppVersion = ''0.1.0.8''' 'expected app version'
    $common = Replace-ExactOnce $common 'GPI_ORDER_INTAKE_AL_AUTHORITY_TEST_ENABLED' $EnableFlag 'enable flag'
    $common = Replace-ExactOnce $common '[int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 0 -and' '[int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 8 -and' 'installed revision'
    $common = Replace-ExactOnce $common '$TestPrefix          = ''AITEST-ALAUTH-''' '$TestPrefix          = ''AITEST-FHNEG8-''' 'test prefix'
    $common = Replace-ExactOnce $common '$HistoricalUnitPrice = [decimal]277.99' '$HistoricalUnitPrice = [decimal]0' 'unused sample price'
    $common = Replace-ExactOnce $common 'Write-Host "Historical Price  : $HistoricalUnitPrice (evidence only; NOT sent)"' 'Write-Host ''Historical Price  : NOT USED - this gate tests fail-closed pricing evidence''' 'historical-price display'

    # Rejection is the expected terminal outcome. Preserve residual-order verification and finally cleanup.
    $common = Replace-ExactOnce $common "throw 'AL authority rejected the request for a non-price reason. See response above.'" "Write-Host 'EXPECTED_FULL_HISTORY_PRICING_REJECTION_REACHED' -ForegroundColor Green`n        return" 'expected rejection terminal'

    if ($common -match '(?i)extensionUpload|extensionContent|Microsoft\.NAV\.upload') {
        throw 'Full-history rejection tester unexpectedly contains extension upload/install operations.'
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 - FULL-HISTORY PRICING-EVIDENCE REJECTION GATE / PRE ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'Environment         : PRE_GAMERDOCS_CUTOVER_20260831 / sandbox'
    Write-Host 'Company             : Gamer Packaging'
    Write-Host "Installed target    : GPI Order Intake $TargetVersion"
    Write-Host "Local package SHA   : $actualHash (verification only)"
    Write-Host 'Evidence source     : corrected full-history GET profile; no $top=500 total-result cap'
    Write-Host 'Pricing key         : customer + item + UOM + location; quantity excluded'
    Write-Host 'Cases               : Vinegar/001 latest-two conflict; Vinegar/002 one observation'
    Write-Host 'Publish / install   : NONE' -ForegroundColor Green
    Write-Host 'Required outcome    : expected HTTP rejection + residualTaggedOrders=0 + no priced Draft marker'
    Write-Host 'Release/Ship/Post   : NOT IMPLEMENTED / BLOCKED'
    Write-Host 'Production          : HARD BLOCKED' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $results = [System.Collections.Generic.List[object]]::new()
    $previousEnable = [Environment]::GetEnvironmentVariable($EnableFlag)
    [Environment]::SetEnvironmentVariable($EnableFlag, 'true')
    try {
        foreach ($case in $Cases) {
            Write-Host ''
            Write-Host ("CASE: {0}" -f $case.name) -ForegroundColor Cyan
            Write-Host ("  Item/Qty/UOM/Location: {0} / {1} {2} / {3}" -f $case.itemNumber, $case.quantity, $case.uom, $case.location)
            Write-Host ("  Expected REVIEW       : {0}" -f $case.reason)

            $test = $common
            $test = Replace-ExactOnce $test '$ItemNumber          = ''C-503003-12033922''' ("`$ItemNumber          = '{0}'" -f $case.itemNumber) "$($case.name) item"
            $test = Replace-ExactOnce $test '$Quantity            = [decimal]56.42' ("`$Quantity            = [decimal]{0}" -f $case.quantity) "$($case.name) quantity"
            $test = Replace-ExactOnce $test '$UnitOfMeasureCode   = ''M''' ("`$UnitOfMeasureCode   = '{0}'" -f $case.uom) "$($case.name) UOM"
            $test = Replace-ExactOnce $test '$LocationCode        = ''00''' ("`$LocationCode        = '{0}'" -f $case.location) "$($case.name) location"
            # ExpectedLocationId is intentionally left at the base value. It is used only on unexpected success; the
            # resolver must reject before a Sales Line read-back. If a Draft unexpectedly survives, the base tester's
            # finally block still performs exact AITEST cleanup before this wrapper fails the case.

            $temp = Join-Path $PSScriptRoot ('.GPIOrderIntake-FullHistoryNeg018-' + $case.name + '-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
            try {
                Set-Content -LiteralPath $temp -Value $test -Encoding UTF8 -NoNewline
                $output = @(& $temp *>&1)
                $text = ($output | Out-String)
                $output | ForEach-Object { Write-Host ([string]$_) }

                if ($text.IndexOf('EXPECTED_FULL_HISTORY_PRICING_REJECTION_REACHED', [StringComparison]::Ordinal) -lt 0) {
                    throw "$($case.name): expected pricing rejection marker was not reached."
                }
                if ($text -notmatch [regex]::Escape([string]$case.expectedPattern)) {
                    throw "$($case.name): expected resolver error pattern not found: $($case.expectedPattern)"
                }
                if ($text -notmatch '"residualTaggedOrders"\s*:\s*0') {
                    throw "$($case.name): zero residualTaggedOrders proof was not found."
                }
                if ($text.IndexOf('Cleanup: NOT NEEDED - no tagged order remained.', [StringComparison]::Ordinal) -lt 0) {
                    throw "$($case.name): no-residual cleanup confirmation was not found."
                }
                if ($text.IndexOf('AL_AUTHORITY_CREATED_PRICED_DRAFT', [StringComparison]::Ordinal) -ge 0) {
                    throw "$($case.name): unexpected priced Draft marker found."
                }

                $results.Add([pscustomobject][ordered]@{
                    case=$case.name
                    outcome='EXPECTED_PRICING_REJECTION'
                    residualTaggedOrders=0
                    salesOrderCreated=$false
                })
                Write-Host ("{0}: PASS" -f $case.name) -ForegroundColor Green
            }
            finally {
                Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
            }
        }
    }
    finally {
        if ($null -eq $previousEnable) {
            Remove-Item "Env:$EnableFlag" -ErrorAction SilentlyContinue
        }
        else {
            [Environment]::SetEnvironmentVariable($EnableFlag, $previousEnable)
        }
    }

    if ($results.Count -ne $Cases.Count) { throw "Expected $($Cases.Count) full-history rejection passes; got $($results.Count)." }

    Write-Host ''
    $results | Format-Table -AutoSize | Out-Host
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 FULL-HISTORY PRICING-EVIDENCE REJECTION GATE: PASS' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan
}
finally {
    Pop-Location
}
