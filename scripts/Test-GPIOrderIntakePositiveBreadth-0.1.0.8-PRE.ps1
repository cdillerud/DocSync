#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# PRE-ONLY POSITIVE BREADTH MATRIX FOR ALREADY-INSTALLED GPI ORDER INTAKE 0.1.0.8
#
# Reuses the proven no-publish authority tester as the only create/read/cleanup implementation.
# No extension upload/install occurs here. Each case creates one exact AITEST Draft, requires exact quantity and
# context price read-back, and requires mandatory cleanup before the next case begins.
# =====================================================================================================================
$ExpectedBaseBlob = '3e7b89f63dd058ab9c402980554b5bc62def144d'
$BasePath = 'scripts/Test-GPIOrderIntakeALAuthority-PRE.ps1'
$TargetVersion = '0.1.0.8'
$ExpectedPackageHash = '6C8E9AA69685622073294B21B54F92032887DDE66D49018075D88E624D22389A'
$EnableFlag = 'GPI_ORDER_INTAKE_POSITIVE_BREADTH_018_ENABLED'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$PackagePath = Join-Path $RepoRoot 'order-intake-bc\.output\Gamer Packaging Inc_GPI Order Intake_0.1.0.8.app'

# Representative live contexts selected from the GET-only positive-candidate profile.
# Quantities are historically observed examples, not fixed rules. The PO owns quantity; pricing excludes quantity.
$Cases = @(
    [pscustomobject][ordered]@{
        name='PIZZA_00_VARIABLE_QTY'
        product='14oz Pizza'
        itemNumber='C-8479-10000229'
        quantity='61.425'
        uom='M'
        location='00'
        locationId='53ec399a-c4e1-eb11-abff-7c05070e4047'
        expectedPrice='196.43'
        prefix='AITEST-BR8-PZ-'
    },
    [pscustomobject][ordered]@{
        name='SALSA16_00_VARIABLE_QTY'
        product='16oz Salsa'
        itemNumber='C-503004-12033478'
        quantity='85.932'
        uom='M'
        location='00'
        locationId='53ec399a-c4e1-eb11-abff-7c05070e4047'
        expectedPrice='217.67'
        prefix='AITEST-BR8-S16-'
    },
    [pscustomobject][ordered]@{
        name='VINEGAR_082_VARIABLE_QTY'
        product='16oz Vinegar'
        itemNumber='C-8808-12026443'
        quantity='49.742'
        uom='M'
        location='082'
        locationId='8cec399a-c4e1-eb11-abff-7c05070e4047'
        expectedPrice='188.01'
        prefix='AITEST-BR8-VN-'
    },
    [pscustomobject][ordered]@{
        name='SALSA24_082_VARIABLE_QTY'
        product='24oz Salsa'
        itemNumber='C-503003-12033922'
        quantity='33.852'
        uom='M'
        location='082'
        locationId='8cec399a-c4e1-eb11-abff-7c05070e4047'
        expectedPrice='289.49'
        prefix='AITEST-BR8-S24-'
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

    if ($common -match '(?i)extensionUpload|extensionContent|Microsoft\.NAV\.upload') {
        throw 'Positive breadth tester unexpectedly contains extension upload/install operations.'
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 - POSITIVE VARIABLE-PO BREADTH MATRIX / PRE ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'Environment         : PRE_GAMERDOCS_CUTOVER_20260831 / sandbox'
    Write-Host 'Company             : Gamer Packaging'
    Write-Host "Installed target    : GPI Order Intake $TargetVersion"
    Write-Host "Local package SHA   : $actualHash (verification only)"
    Write-Host 'Publish / install   : NONE'
    Write-Host "Positive cases      : $($Cases.Count)"
    Write-Host 'Quantity policy     : incoming PO owns quantity; historical quantities are evidence, not fixed requirements'
    Write-Host 'Pricing key         : customer + item + UOM + location; quantity excluded'
    Write-Host 'Required per case   : exact quantity + expected context price + exact AITEST cleanup'
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
            Write-Host ("  Product            : {0}" -f $case.product)
            Write-Host ("  Item/Qty/UOM       : {0} / {1} {2}" -f $case.itemNumber, $case.quantity, $case.uom)
            Write-Host ("  Location / Price   : {0} / {1}" -f $case.location, $case.expectedPrice)

            $test = $common
            $test = Replace-ExactOnce $test '$ItemNumber          = ''C-503003-12033922''' ("`$ItemNumber          = '{0}'" -f $case.itemNumber) "$($case.name) item"
            $test = Replace-ExactOnce $test '$Quantity            = [decimal]56.42' ("`$Quantity            = [decimal]{0}" -f $case.quantity) "$($case.name) quantity"
            $test = Replace-ExactOnce $test '$UnitOfMeasureCode   = ''M''' ("`$UnitOfMeasureCode   = '{0}'" -f $case.uom) "$($case.name) UOM"
            $test = Replace-ExactOnce $test '$LocationCode        = ''00''' ("`$LocationCode        = '{0}'" -f $case.location) "$($case.name) location"
            $test = Replace-ExactOnce $test '$ExpectedLocationId  = ''53ec399a-c4e1-eb11-abff-7c05070e4047''' ("`$ExpectedLocationId  = '{0}'" -f $case.locationId) "$($case.name) location ID"
            $test = Replace-ExactOnce $test '$HistoricalUnitPrice = [decimal]277.99' ("`$HistoricalUnitPrice = [decimal]{0}" -f $case.expectedPrice) "$($case.name) expected price"
            $test = Replace-ExactOnce $test '$TestPrefix          = ''AITEST-ALAUTH-''' ("`$TestPrefix          = '{0}'" -f $case.prefix) "$($case.name) test prefix"

            $oldFinalPass = "Write-Host 'GPI ORDER INTAKE AL AUTHORITY ROUND-TRIP: PASS' -ForegroundColor Green"
            $newFinalPass = @"
if (`$pricingResult -ne 'MATCHED_HISTORICAL_LOCATION_PRICE') {
    throw '$($case.name): cleaned up safely but context price did not equal $($case.expectedPrice).'
}
Write-Host '$($case.name): EXACT QUANTITY + CONTEXT PRICE + CLEANUP PASS' -ForegroundColor Green
"@.TrimEnd("`r","`n")
            $test = Replace-ExactOnce $test $oldFinalPass $newFinalPass "$($case.name) final PASS"

            $temp = Join-Path $PSScriptRoot ('.GPIOrderIntake-PositiveBreadth018-' + $case.name + '-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
            try {
                Set-Content -LiteralPath $temp -Value $test -Encoding UTF8 -NoNewline
                $output = @(& $temp *>&1)
                $text = ($output | Out-String)
                $output | ForEach-Object { Write-Host ([string]$_) }

                $requiredMarker = "$($case.name): EXACT QUANTITY + CONTEXT PRICE + CLEANUP PASS"
                if ($text.IndexOf($requiredMarker, [StringComparison]::Ordinal) -lt 0) {
                    throw "$($case.name): exact positive PASS marker was not reached."
                }
                if ($text.IndexOf('AL_AUTHORITY_CREATED_PRICED_DRAFT', [StringComparison]::Ordinal) -lt 0) {
                    throw "$($case.name): priced Draft creation marker was not found."
                }
                if ($text.IndexOf('Cleanup: PASS', [StringComparison]::Ordinal) -lt 0) {
                    throw "$($case.name): mandatory cleanup PASS marker was not found."
                }
                if ($text -notmatch ('"quantity"\s*:\s*' + [regex]::Escape([string]$case.quantity))) {
                    throw "$($case.name): exact quantity read-back proof was not found."
                }
                if ($text -notmatch ('"observedUnitPrice"\s*:\s*' + [regex]::Escape([string]$case.expectedPrice))) {
                    throw "$($case.name): exact price read-back proof was not found."
                }

                $results.Add([pscustomobject][ordered]@{
                    case=$case.name
                    product=$case.product
                    item=$case.itemNumber
                    quantity=[decimal]$case.quantity
                    uom=$case.uom
                    location=$case.location
                    observedPrice=[decimal]$case.expectedPrice
                    cleanup='PASS'
                })
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

    if ($results.Count -ne $Cases.Count) { throw "Expected $($Cases.Count) positive passes; got $($results.Count)." }

    Write-Host ''
    $results | Format-Table -AutoSize | Out-Host
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 POSITIVE VARIABLE-PO BREADTH MATRIX: PASS' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan
}
finally {
    Pop-Location
}
