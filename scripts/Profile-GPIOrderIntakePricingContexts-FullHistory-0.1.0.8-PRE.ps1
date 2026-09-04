#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# PRE-ONLY / GET-ONLY full-history wrapper over the committed 0.1.0.8 pricing-context profiler.
# Corrects the prior profiler's `$top=500 total-result cap before any new positive write tests are allowed.
# No extension mutation. No Sales Order action. No business-data writes.
# =====================================================================================================================
$ExpectedBaseBlob = 'e9923c0e6abc36b7ec4abd777093578557684cc4'
$BasePath = 'scripts/Profile-GPIOrderIntakePricingContexts-0.1.0.8-PRE.ps1'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Replace-ExactOnce {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Name
    )
    $count = ([regex]::Matches($Text, [regex]::Escape($Old))).Count
    Write-Host ("Patch target {0,-30}: {1} / 1" -f $Name, $count)
    if ($count -ne 1) { throw "Expected exactly one $Name patch target; found $count." }
    return $Text.Replace($Old, $New)
}

Push-Location $RepoRoot
try {
    $headBlob = (& git rev-parse "HEAD:$BasePath").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($headBlob)) {
        throw "Could not resolve committed base profiler at HEAD:$BasePath"
    }
    if ($headBlob -ne $ExpectedBaseBlob) {
        throw "Committed pricing-context profiler changed. Expected $ExpectedBaseBlob; got $headBlob."
    }

    $base = (& git show "HEAD:$BasePath") -join "`n"
    if ([string]::IsNullOrWhiteSpace($base)) { throw 'Committed base profiler content was empty.' }

    $oldQuery = '$rows = @(Invoke-BcGetAll "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$filter&`$top=500" $headers)'
    $newQuery = '$rows = @(Invoke-BcGetAll "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$filter" $headers -MaxPages 50)'
    $patched = Replace-ExactOnce $base $oldQuery $newQuery 'remove total-result cap'

    $oldAgree = '$agree = @($ordered | Where-Object {[string]$_.decision -eq ''PASS_LATEST_TWO_AGREE''})'
    $candidateOutput = @'
$agree = @($ordered | Where-Object {[string]$_.decision -eq 'PASS_LATEST_TWO_AGREE'})

Write-Host ''
Write-Host 'FULL_HISTORY_POSITIVE_CANDIDATES' -ForegroundColor Green
foreach ($row in @($agree | Where-Object {[string]$_.role -eq 'NORMAL'} | Sort-Object product,locationCode)) {
    $quantityText = @($row.distinctQuantities | ForEach-Object {
        ([decimal]$_).ToString([System.Globalization.CultureInfo]::InvariantCulture)
    }) -join ','
    $priceText = ([decimal]$row.latestPrice).ToString([System.Globalization.CultureInfo]::InvariantCulture)
    $secondPriceText = ([decimal]$row.secondLatestPrice).ToString([System.Globalization.CultureInfo]::InvariantCulture)
    Write-Host ('FULLCANDIDATE|product={0}|item={1}|uom={2}|location={3}|rows={4}|latestPrice={5}|secondLatestPrice={6}|latestDocument={7}|secondLatestDocument={8}|observedQuantities={9}' -f
        [string]$row.product,
        [string]$row.itemNumber,
        [string]$row.uom,
        [string]$row.locationCode,
        [int]$row.rowCount,
        $priceText,
        $secondPriceText,
        [string]$row.latestDocument,
        [string]$row.secondLatestDocument,
        $quantityText)
}
'@.TrimEnd("`r","`n")
    $patched = Replace-ExactOnce $patched $oldAgree $candidateOutput 'full-history candidate output'

    $oldTitle = "Write-Host 'GPI ORDER INTAKE 0.1.0.8 - GIOVANNI PRICING-CONTEXT PROFILE / PRE GET ONLY' -ForegroundColor Cyan"
    $newTitle = "Write-Host 'GPI ORDER INTAKE 0.1.0.8 - GIOVANNI FULL-HISTORY PRICING-CONTEXT PROFILE / PRE GET ONLY' -ForegroundColor Cyan"
    $patched = Replace-ExactOnce $patched $oldTitle $newTitle 'profile title'

    if ($patched -match '(?i)Invoke-RestMethod\s+-Method\s+(Post|Patch|Delete)|Invoke-WebRequest\s+-Method\s+(Post|Patch|Delete)|extensionUpload|Microsoft\.NAV\.upload|createValidatedDraft') {
        throw 'Full-history profiler unexpectedly contains mutation/action operations.'
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 - FULL-HISTORY PRICING EVIDENCE RECHECK / PRE GET ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed base blob : $headBlob"
    Write-Host 'Correction           : removes prior `$top=500 total-result cap'
    Write-Host 'Retrieval            : follow OData nextLink until exhausted (max 50 pages safety bound)'
    Write-Host 'Pricing key          : customer + item + UOM + location; quantity excluded'
    Write-Host 'HTTP methods         : GET ONLY' -ForegroundColor Green
    Write-Host 'Extension mutation   : NONE' -ForegroundColor Green
    Write-Host 'Business data write  : NONE' -ForegroundColor Green
    Write-Host 'Sales-order action   : NOT CALLED' -ForegroundColor Green
    Write-Host 'Production           : HARD BLOCKED' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $temp = Join-Path $PSScriptRoot ('.GPIOrderIntake-FullHistoryProfile018-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $temp -Value $patched -Encoding UTF8 -NoNewline
        & $temp
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "Full-history pricing profiler exited with code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }

    Write-Host ''
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 FULL-HISTORY PRICING PROFILE: GET-ONLY PASS' -ForegroundColor Green
}
finally {
    Pop-Location
}
