#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# =====================================================================================================================
# GET-ONLY wrapper over the committed 0.1.0.8 pricing-context profiler.
# Adds concise pipe-delimited NORMAL + latest-two-agreement candidate records so exact prices/quantities are not lost
# to Format-Table truncation. No extension mutation. No Sales Order action. No business-data writes.
# =====================================================================================================================
$ExpectedBaseBlob = 'e9923c0e6abc36b7ec4abd777093578557684cc4'
$BasePath = 'scripts/Profile-GPIOrderIntakePricingContexts-0.1.0.8-PRE.ps1'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

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

    # Anchor on one unique single line rather than a newline-sensitive multi-line block.
    $anchor = '$agree = @($ordered | Where-Object {[string]$_.decision -eq ''PASS_LATEST_TWO_AGREE''})'
    $candidateBlock = @'

Write-Host ''
Write-Host 'POSITIVE_BREADTH_CANDIDATES' -ForegroundColor Green
foreach ($row in @($agree | Where-Object {[string]$_.role -eq 'NORMAL'} | Sort-Object product,locationCode)) {
    $quantityText = @($row.distinctQuantities | ForEach-Object {
        ([decimal]$_).ToString([System.Globalization.CultureInfo]::InvariantCulture)
    }) -join ','
    $priceText = ([decimal]$row.latestPrice).ToString([System.Globalization.CultureInfo]::InvariantCulture)
    Write-Host ('CANDIDATE|product={0}|item={1}|uom={2}|location={3}|price={4}|rows={5}|observedQuantities={6}' -f
        [string]$row.product,
        [string]$row.itemNumber,
        [string]$row.uom,
        [string]$row.locationCode,
        $priceText,
        [int]$row.rowCount,
        $quantityText)
}
'@.TrimEnd("`r","`n")

    $anchorCount = ([regex]::Matches($base, [regex]::Escape($anchor))).Count
    Write-Host "Candidate anchor count : $anchorCount / 1"
    if ($anchorCount -ne 1) { throw "Expected one candidate anchor; found $anchorCount." }
    $patched = $base.Replace($anchor, $anchor + $candidateBlock)

    if ($patched.IndexOf('POSITIVE_BREADTH_CANDIDATES', [StringComparison]::Ordinal) -lt 0) {
        throw 'Positive-candidate output marker missing after patch.'
    }
    if ($patched -match '(?i)Invoke-RestMethod\s+-Method\s+(Post|Patch|Delete)|Invoke-WebRequest\s+-Method\s+(Post|Patch|Delete)|extensionUpload|Microsoft\.NAV\.upload|createValidatedDraft') {
        throw 'Positive-candidate profiler unexpectedly contains mutation/action operations.'
    }

    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 - POSITIVE CANDIDATE PROFILE / PRE GET ONLY' -ForegroundColor Cyan
    Write-Host ('=' * 120) -ForegroundColor Cyan
    Write-Host "Committed base blob : $headBlob"
    Write-Host 'Pricing key         : customer + item + UOM + location; quantity excluded'
    Write-Host 'Output              : only NORMAL contexts whose latest two posted prices agree'
    Write-Host 'HTTP methods        : GET ONLY' -ForegroundColor Green
    Write-Host 'Extension mutation  : NONE' -ForegroundColor Green
    Write-Host 'Business data write : NONE' -ForegroundColor Green
    Write-Host 'Sales-order action  : NOT CALLED' -ForegroundColor Green
    Write-Host 'Production          : HARD BLOCKED' -ForegroundColor Green
    Write-Host ('=' * 120) -ForegroundColor Cyan

    $temp = Join-Path $PSScriptRoot ('.GPIOrderIntake-PositiveCandidates018-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
    try {
        Set-Content -LiteralPath $temp -Value $patched -Encoding UTF8 -NoNewline
        & $temp
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "Patched positive-candidate profiler exited with code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
    }

    Write-Host ''
    Write-Host 'GPI ORDER INTAKE 0.1.0.8 POSITIVE CANDIDATE PROFILE: GET-ONLY PASS' -ForegroundColor Green
}
finally {
    Pop-Location
}
