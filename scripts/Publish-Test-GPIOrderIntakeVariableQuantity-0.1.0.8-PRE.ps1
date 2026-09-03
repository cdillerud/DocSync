#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# CERTIFIED PRE-ONLY WRAPPER OVER THE PROVEN AL PUBLISH/TEST HARNESS.
# Publishes only the exact compiled GPI Order Intake 0.1.0.8 package SHA, then executes one tagged Giovanni round trip
# using a quantity deliberately different from the original 56.42 M proof case. Price must still resolve from
# customer + item + UOM + location context, and mandatory cleanup must leave zero residual AITEST orders.
# =====================================================================================================================
$ExpectedBaseBlob = '5583c0ad8f6a1ae8cf6f49466ab818b849bf0d16'
$BasePath = 'scripts/Publish-Test-GPIOrderIntakeAL-PRE.ps1'
$ExpectedPackageHash = '6C8E9AA69685622073294B21B54F92032887DDE66D49018075D88E624D22389A'
$TargetVersion = '0.1.0.8'
$EnableFlag = 'GPI_ORDER_INTAKE_VARIABLE_QTY_PRE_TEST_ENABLED'
$VariableQuantity = '56.357'
$ExpectedUnitPrice = '277.99'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Replace-ExactCount {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][int]$ExpectedCount,
        [Parameter(Mandatory)][string]$Name
    )

    $count = ([regex]::Matches($Text, [regex]::Escape($Old))).Count
    Write-Host ("Patch target {0,-22}: {1} / {2}" -f $Name, $count, $ExpectedCount)
    if ($count -ne $ExpectedCount) {
        throw "Expected exactly $ExpectedCount $Name patch target(s); found $count."
    }
    return $Text.Replace($Old, $New)
}

Push-Location $RepoRoot
try {
    $headBlob = (& git rev-parse "HEAD:$BasePath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($headBlob)) {
        throw "Could not resolve committed base harness at HEAD:$BasePath"
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 - VARIABLE-QUANTITY RESOLVER PUBLISH + ROUND TRIP / PRE ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Expected base blob   : $ExpectedBaseBlob"
    Write-Host "HEAD base blob       : $headBlob"
    if ($headBlob -ne $ExpectedBaseBlob) { throw 'Committed base publish/test harness blob changed. Review required.' }
    Write-Host 'Committed harness    : PASS' -ForegroundColor Green
    Write-Host "Target version       : $TargetVersion"
    Write-Host "Expected package SHA : $ExpectedPackageHash"
    Write-Host 'Target environment   : PRE_GAMERDOCS_CUTOVER_20260831 / sandbox'
    Write-Host 'Target company       : Gamer Packaging'
    Write-Host "Controlled case      : GIOVANN / C-503003-12033922 / $VariableQuantity M / Location 00"
    Write-Host 'Baseline proof qty   : 56.42 M (NOT used in this round trip)'
    Write-Host "Required read-back   : preserve $VariableQuantity M and Unit Price $ExpectedUnitPrice"
    Write-Host 'Price key            : customer + item + UOM + location; quantity excluded'
    Write-Host 'Cleanup              : MANDATORY exact AITEST Open/Draft only'
    Write-Host 'Release/Ship/Post    : NOT IMPLEMENTED / BLOCKED'
    Write-Host 'Production           : HARD BLOCKED'
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $base = (& git show "HEAD:$BasePath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($base)) { throw 'Committed base harness content was empty.' }

    $patched = $base
    $patched = Replace-ExactCount $patched '0.1.0.0' $TargetVersion 4 'version strings'
    $patched = Replace-ExactCount $patched 'D92A5D2F724F258A690ED0F4E54219A6FE4C9ABCFE3A7FCB731C21E33E266E44' $ExpectedPackageHash 1 'package SHA'
    $patched = Replace-ExactCount $patched 'GPI_ORDER_INTAKE_AL_PRE_TEST_ENABLED' $EnableFlag 1 'enable flag'
    $patched = Replace-ExactCount $patched '[int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 0 -and' '[int]$_.versionBuild -eq 0 -and [int]$_.versionRevision -eq 8 -and' 2 'installed revision'
    $patched = Replace-ExactCount $patched '$Quantity            = [decimal]56.42' '$Quantity            = [decimal]56.357' 1 'variable quantity'

    # Strengthen the final success condition: after mandatory cleanup, both the different input quantity and the
    # context-resolved price must have survived the round trip exactly.
    $oldFinalPass = "Write-Host 'GPI ORDER INTAKE AL AUTHORITY ROUND-TRIP: PASS' -ForegroundColor Green"
    $newFinalPass = @'
if ([decimal]$line.quantity -ne [decimal]56.357) {
    throw "Variable-quantity proof cleaned up safely but read-back quantity was $($line.quantity), expected 56.357."
}
if ($pricingResult -ne 'MATCHED_HISTORICAL_LOCATION_PRICE') {
    throw "Variable-quantity proof cleaned up safely but returned Unit Price $observedPrice instead of required 277.99."
}
Write-Host 'Variable-quantity assertion: PASS (56.357 M preserved)' -ForegroundColor Green
Write-Host 'Resolver context-price assertion: PASS (277.99)' -ForegroundColor Green
Write-Host 'GPI ORDER INTAKE 0.1.0.8 VARIABLE-QUANTITY RESOLVER ROUND-TRIP: PASS' -ForegroundColor Green
'@.TrimEnd("`r","`n")

    $patched = Replace-ExactCount $patched $oldFinalPass $newFinalPass 1 'final PASS'

    if ($patched -match '0\.1\.0\.0') { throw 'Old app version marker remains after patching.' }
    if ($patched -match 'versionRevision\s+-eq\s+0') { throw 'Old installed revision check remains after patching.' }
    if ($patched -match 'D92A5D2F724F258A690ED0F4E54219A6FE4C9ABCFE3A7FCB731C21E33E266E44') { throw 'Old package SHA remains after patching.' }
    if ($patched -match 'GPI_ORDER_INTAKE_AL_PRE_TEST_ENABLED') { throw 'Old enable flag remains after patching.' }
    if ($patched -match '\$Quantity\s*=\s*\[decimal\]56\.42') { throw 'Original fixed proof quantity remains as the action quantity.' }
    if ($patched.IndexOf('MATCHED_HISTORICAL_LOCATION_PRICE', [StringComparison]::Ordinal) -lt 0) { throw 'Price assertion marker missing.' }

    $tempScript = Join-Path $PSScriptRoot ('.GPIOrderIntake-VariableQtyPublishTest-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $tempScript -Value $patched -Encoding UTF8 -NoNewline
        Write-Host 'Variable-quantity harness patch: PASS' -ForegroundColor Green
        Write-Host ''

        $previous = [Environment]::GetEnvironmentVariable($EnableFlag)
        [Environment]::SetEnvironmentVariable($EnableFlag, 'true')
        try {
            & $tempScript
            if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
                throw "Variable-quantity publish/test harness exited with code $LASTEXITCODE."
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
