#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# PRE-ONLY FAIL-CLOSED GATE FOR ALREADY-INSTALLED GPI ORDER INTAKE 0.1.0.8
#
# Uses the proven no-publish authority tester as the only create/read/cleanup implementation.
# No extension upload/install occurs here. Each case must be rejected before draft creation and prove zero residual AITEST rows.
# =====================================================================================================================
$ExpectedBaseBlob = '3e7b89f63dd058ab9c402980554b5bc62def144d'
$BasePath = 'scripts/Test-GPIOrderIntakeALAuthority-PRE.ps1'
$TargetVersion = '0.1.0.8'
$ExpectedPackageHash = '6C8E9AA69685622073294B21B54F92032887DDE66D49018075D88E624D22389A'
$EnableFlag = 'GPI_ORDER_INTAKE_RESOLVER_FAILCLOSED_018_ENABLED'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PackagePath = Join-Path $RepoRoot 'order-intake-bc\.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.8.app'

$Cases = @(
    [pscustomobject][ordered]@{
        name = 'REAL_PRICE_CONFLICT_PIZZA_082'
        itemNumber = 'C-8479-10000229'
        quantity = '89.775'
        uom = 'M'
        location = '082'
        locationId = '8cec399a-c4e1-eb11-abff-7c05070e4047'
        expectedPattern = 'two most recent pricing-context posted invoices disagree on Unit Price'
        reason = 'Live GET-only profile: Pizza / M / 082 is REVIEW_LATEST_TWO_DISAGREE.'
    },
    [pscustomobject][ordered]@{
        name = 'PASTA_QUANTITY_SOURCE_AMBIGUITY'
        itemNumber = 'C-9874-10001833'
        quantity = '62.062'
        uom = 'M'
        location = '00'
        locationId = '53ec399a-c4e1-eb11-abff-7c05070e4047'
        expectedPattern = 'quantity-source REVIEW required for Giovanni 24oz Pasta'
        reason = 'Current Giovanni blanket source does not state quantity; repeated historical quantities do not resolve source intent.'
    },
    [pscustomobject][ordered]@{
        name = 'MIXED_SALSA_SOURCE_EXCEPTION'
        itemNumber = 'C-8682-12013925'
        quantity = '5.642'
        uom = 'M'
        location = '082'
        locationId = '8cec399a-c4e1-eb11-abff-7c05070e4047'
        expectedPattern = 'exception REVIEW required for Giovanni mixed/exception Salsa'
        reason = 'Explicit mixed/exception item remains REVIEW even when pricing history is stable.'
    },
    [pscustomobject][ordered]@{
        name = 'INVALID_BC_UOM'
        itemNumber = 'C-503003-12033922'
        quantity = '56.357'
        uom = 'BOX'
        location = '00'
        locationId = '53ec399a-c4e1-eb11-abff-7c05070e4047'
        expectedPattern = 'UOM BOX is not configured for the item in Business Central'
        reason = 'Requested UOM must exist on the BC item; quantity itself remains variable.'
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
    if ($count -ne 1) { throw "Expected exactly one $Name patch target; found $count." }
    return $Text.Replace($Old, $New)
}

Push-Location $RepoRoot
try {
    $headBlob = (& git rev-parse "HEAD:$BasePath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($headBlob)) {
        throw "Could not resolve committed base tester at HEAD:$BasePath"
    }
    if ($headBlob -ne $ExpectedBaseBlob) { throw 'Committed no-publish authority tester changed. Review required.' }

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
    $common = Replace-ExactOnce $common '$TestPrefix          = ''AITEST-ALAUTH-''' '$TestPrefix          = ''AITEST-NEG8-''' 'test prefix'

    # Rejection is the expected terminal outcome. Preserve all residual-order checks and the finally cleanup path.
    $common = Replace-ExactOnce $common "throw 'AL authority rejected the request for a non-price reason. See response above.'" "Write-Host 'EXPECTED_RESOLVER_REJECTION_REACHED' -ForegroundColor Green`n        return" 'expected-rejection terminal'

    if ($common -match '(?i)extensionUpload|extensionContent|Microsoft\.NAV\.upload') {
        throw 'Fail-closed tester unexpectedly contains extension upload/install operations.'
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 - FAIL-CLOSED RESOLVER GATE / PRE ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'Environment         : PRE_GAMERDOCS_CUTOVER_20260831 / sandbox'
    Write-Host 'Company             : Gamer Packaging'
    Write-Host "Installed target    : GPI Order Intake $TargetVersion"
    Write-Host "Local package SHA   : $actualHash (verification only)"
    Write-Host 'Publish / install   : NONE'
    Write-Host "Negative cases      : $($Cases.Count)"
    Write-Host 'Quantity policy     : DIFFERENT IS NOT WRONG; incoming PO quantity is preserved when structurally valid'
    Write-Host 'Required outcome    : expected resolver rejection + zero residual AITEST orders for every case'
    Write-Host 'Release/Ship/Post   : NOT IMPLEMENTED / BLOCKED'
    Write-Host 'Production          : HARD BLOCKED'
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $results = [System.Collections.Generic.List[object]]::new()
    $previousEnable = [Environment]::GetEnvironmentVariable($EnableFlag)
    [Environment]::SetEnvironmentVariable($EnableFlag, 'true')
    try {
        foreach ($case in $Cases) {
            Write-Host ''
            Write-Host ("CASE: {0}" -f $case.name) -ForegroundColor Cyan
            Write-Host ("  Item/Qty/UOM/Location: {0} / {1} {2} / {3}" -f $case.itemNumber, $case.quantity, $case.uom, $case.location)
            Write-Host ("  Why this should REVIEW: {0}" -f $case.reason)

            $test = $common
            $test = Replace-ExactOnce $test '$ItemNumber          = ''C-503003-12033922''' ("`$ItemNumber          = '{0}'" -f $case.itemNumber) "$($case.name) item"
            $test = Replace-ExactOnce $test '$Quantity            = [decimal]56.42' ("`$Quantity            = [decimal]{0}" -f $case.quantity) "$($case.name) quantity"
            $test = Replace-ExactOnce $test '$UnitOfMeasureCode   = ''M''' ("`$UnitOfMeasureCode   = '{0}'" -f $case.uom) "$($case.name) UOM"
            $test = Replace-ExactOnce $test '$LocationCode        = ''00''' ("`$LocationCode        = '{0}'" -f $case.location) "$($case.name) location"
            $test = Replace-ExactOnce $test '$ExpectedLocationId  = ''53ec399a-c4e1-eb11-abff-7c05070e4047''' ("`$ExpectedLocationId  = '{0}'" -f $case.locationId) "$($case.name) location ID"

            $temp = Join-Path $PSScriptRoot ('.GPIOrderIntake-FailClosed018-' + $case.name + '-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
            try {
                Set-Content -LiteralPath $temp -Value $test -Encoding UTF8 -NoNewline
                $output = @(& $temp *>&1)
                $text = ($output | Out-String)
                $output | ForEach-Object { Write-Host ([string]$_) }

                if ($text.IndexOf('EXPECTED_RESOLVER_REJECTION_REACHED', [StringComparison]::Ordinal) -lt 0) {
                    throw "$($case.name): expected resolver rejection marker was not reached."
                }
                if ($text -notmatch [regex]::Escape([string]$case.expectedPattern)) {
                    throw "$($case.name): expected error pattern not found: $($case.expectedPattern)"
                }
                if ($text -notmatch '"residualTaggedOrders"\s*:\s*0') {
                    throw "$($case.name): zero residualTaggedOrders proof was not found."
                }
                if ($text.IndexOf('Cleanup: NOT NEEDED - no tagged order remained.', [StringComparison]::Ordinal) -lt 0) {
                    throw "$($case.name): cleanup/no-residual confirmation was not found."
                }
                if ($text.IndexOf('AL_AUTHORITY_CREATED_PRICED_DRAFT', [StringComparison]::Ordinal) -ge 0) {
                    throw "$($case.name): unexpected priced draft success marker found."
                }

                $results.Add([pscustomobject][ordered]@{
                    case = $case.name
                    outcome = 'EXPECTED_REJECTION'
                    residualTaggedOrders = 0
                    salesOrderCreated = $false
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

    if ($results.Count -ne $Cases.Count) { throw "Expected $($Cases.Count) passing rejection cases; got $($results.Count)." }

    Write-Host ''
    $results | Format-Table -AutoSize | Out-Host
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 FAIL-CLOSED RESOLVER GATE: PASS' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan
}
finally {
    Pop-Location
}
