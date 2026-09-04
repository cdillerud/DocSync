#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedSourceBlob = '62b76f44bbc59996fe625d7f15a988a02eed359b'
$SourceScript = Join-Path $PSScriptRoot 'Profile-GPIOrderIntakeGiovanniResolver-PRE.ps1'

if (-not (Test-Path -LiteralPath $SourceScript)) { throw "Source profiler not found: $SourceScript" }
$ActualSourceBlob = (& git hash-object -- $SourceScript).Trim()

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - GIOVANNI RESOLVER PROFILE REV2 / PRE GET ONLY' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Expected source blob : $ExpectedSourceBlob"
Write-Host "Actual source blob   : $ActualSourceBlob"
if ($ActualSourceBlob -ne $ExpectedSourceBlob) { throw 'Source profiler blob verification failed.' }
Write-Host 'Source blob verification : PASS' -ForegroundColor Green
Write-Host 'Patch scope              : empty-array binding + deterministic Sort-Object + weak-latest-price REVIEW'
Write-Host 'BC operations            : GET ONLY'
Write-Host 'Extension mutation       : NONE'
Write-Host 'Business data writes     : NONE'
Write-Host 'Sales-order action       : NOT CALLED'
Write-Host 'Production               : HARD BLOCKED'
Write-Host ('=' * 120) -ForegroundColor Cyan

$raw = Get-Content -LiteralPath $SourceScript -Raw
$patched = $raw

# PowerShell collection binding must tolerate a valid zero-history result.
$oldCollectionParam = 'param([Parameter(Mandatory)][object[]]$Rows)'
$newCollectionParam = 'param([Parameter(Mandatory)][AllowEmptyCollection()][object[]]$Rows)'
$collectionParamCount = ([regex]::Matches($patched, [regex]::Escape($oldCollectionParam))).Count
if ($collectionParamCount -ne 3) { throw "Expected exactly 3 object-array parameter targets; found $collectionParamCount." }
$patched = $patched.Replace($oldCollectionParam, $newCollectionParam)

# Use explicit calculated-property syntax so descending order is deterministic and parser-safe.
$oldQuantitySort = 'return @($output | Sort-Object count -Descending, quantity -Descending)'
$newQuantitySort = "return @(`$output | Sort-Object -Property @{Expression='count';Descending=`$true}, @{Expression='quantity';Descending=`$true})"
if (([regex]::Matches($patched, [regex]::Escape($oldQuantitySort))).Count -ne 1) { throw 'Quantity/UOM sort patch target not found exactly once.' }
$patched = $patched.Replace($oldQuantitySort, $newQuantitySort)

$oldContextSort = 'return @($output | Sort-Object quantity -Descending, uom, locationCode)'
$newContextSort = "return @(`$output | Sort-Object -Property @{Expression='quantity';Descending=`$true}, @{Expression='uom';Descending=`$false}, @{Expression='locationCode';Descending=`$false})"
if (([regex]::Matches($patched, [regex]::Escape($oldContextSort))).Count -ne 1) { throw 'Price-context sort patch target not found exactly once.' }
$patched = $patched.Replace($oldContextSort, $newContextSort)

# A latest price that has not repeated is evidence, not automatic authority.
$oldResolver = @'
    $resolverDecision = if ([string]$target.role -eq 'EXCEPTION') {
        'REVIEW_EXCEPTION_ONLY_DO_NOT_AUTO_APPLY_TO_NORMAL_ROWS'
    }
    elseif ($quantityStatus -like 'REVIEW*') {
        'REVIEW_QUANTITY_CONTEXT'
    }
    elseif ($locationPriceStatus -eq 'REVIEW_NO_EXPECTED_PRICE_CONTEXT' -or $locationPriceStatus -eq 'REVIEW_PRICE_CONTEXT') {
        'REVIEW_PRICE_CONTEXT'
    }
    elseif ($locationPriceStatus -eq 'LOCATION_REQUIRED_FOR_PRICE') {
        'PASS_WITH_LOCATION_REQUIRED'
    }
    else {
        'PASS_PROFILE_CANDIDATE'
    }
'@.TrimEnd("`r","`n")

$newResolver = @'
    $weakExpectedPriceContexts = @($expectedContexts | Where-Object {
        [string]$_.candidateConfidence -in @('LOW_SINGLE_OBSERVATION','MEDIUM_LATEST_PRICE_CHANGED')
    })

    $resolverDecision = if ([string]$target.role -eq 'EXCEPTION') {
        'REVIEW_EXCEPTION_ONLY_DO_NOT_AUTO_APPLY_TO_NORMAL_ROWS'
    }
    elseif ($quantityStatus -like 'REVIEW*') {
        'REVIEW_QUANTITY_CONTEXT'
    }
    elseif ($locationPriceStatus -eq 'REVIEW_NO_EXPECTED_PRICE_CONTEXT' -or $locationPriceStatus -eq 'REVIEW_PRICE_CONTEXT') {
        'REVIEW_PRICE_CONTEXT'
    }
    elseif ($weakExpectedPriceContexts.Length -gt 0) {
        'REVIEW_LATEST_PRICE_NOT_REPEATED'
    }
    elseif ($locationPriceStatus -eq 'LOCATION_REQUIRED_FOR_PRICE') {
        'PASS_WITH_LOCATION_REQUIRED'
    }
    else {
        'PASS_PROFILE_CANDIDATE'
    }
'@.TrimEnd("`r","`n")

if (([regex]::Matches($patched, [regex]::Escape($oldResolver))).Count -ne 1) { throw 'Resolver-decision patch target not found exactly once.' }
$patched = $patched.Replace($oldResolver, $newResolver)

$oldOutput = @'
        locationPriceStatus = $locationPriceStatus
        resolverDecision = $resolverDecision
'@.TrimEnd("`r","`n")
$newOutput = @'
        locationPriceStatus = $locationPriceStatus
        weakExpectedPriceContextCount = $weakExpectedPriceContexts.Length
        resolverDecision = $resolverDecision
'@.TrimEnd("`r","`n")
if (([regex]::Matches($patched, [regex]::Escape($oldOutput))).Count -ne 1) { throw 'Profile-output patch target not found exactly once.' }
$patched = $patched.Replace($oldOutput, $newOutput)

$tempScript = Join-Path $PSScriptRoot ('.GPIOrderIntake-GiovanniResolverProfile-REV2-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
try {
    Set-Content -LiteralPath $tempScript -Value $patched -Encoding UTF8 -NoNewline
    Write-Host 'REV2 profiler hardening : PASS' -ForegroundColor Green
    Write-Host 'Starting GET-only Giovanni-wide profile...' -ForegroundColor Cyan
    Write-Host ''
    & $tempScript
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "Patched profiler exited with code $LASTEXITCODE." }
}
finally {
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'GPI ORDER INTAKE GIOVANNI RESOLVER PROFILE REV2: WRAPPER COMPLETE' -ForegroundColor Green
