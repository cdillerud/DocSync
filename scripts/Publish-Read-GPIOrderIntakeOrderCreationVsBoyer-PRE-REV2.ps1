#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedSourceBlob = '0a1abca753d926407b040cde6461d1fcf0570814'
$SourceScript = Join-Path $PSScriptRoot 'Publish-Read-GPIOrderIntakeOrderCreationVsBoyer-PRE.ps1'

if (-not (Test-Path -LiteralPath $SourceScript)) { throw "Source diagnostic not found: $SourceScript" }
$ActualSourceBlob = (& git hash-object -- $SourceScript).Trim()

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - ORDER CREATION VS BOYER REV2 / CARRIED-FIELD-AWARE' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Expected source blob : $ExpectedSourceBlob"
Write-Host "Actual source blob   : $ActualSourceBlob"
if ($ActualSourceBlob -ne $ExpectedSourceBlob) { throw 'Source diagnostic blob verification failed.' }
Write-Host 'Source blob verification: PASS' -ForegroundColor Green
Write-Host 'Comparison scope        : Qty + UOM + Unit Price are Boyer-carried fields; Location reported separately'
Write-Host 'BC write scope          : extension upgrade only if 0.1.0.6 not already installed'
Write-Host 'Business data writes    : NONE'
Write-Host 'Sales-order action      : NOT CALLED'
Write-Host 'Production              : HARD BLOCKED'
Write-Host ('=' * 120) -ForegroundColor Cyan

$raw = Get-Content -LiteralPath $SourceScript -Raw

$old1 = '            $matches = ([decimal]$line.quantity -eq [decimal]$p.quantity -and [string]$line.unitOfMeasureCode -eq [string]$p.unitOfMeasureCode -and [decimal]$line.unitPrice -eq [decimal]$p.unitPrice -and [string]$line.locationCode -eq [string]$p.locationCode)'
$new1 = @'
            $carriedFieldsMatch = ([decimal]$line.quantity -eq [decimal]$p.quantity -and [string]$line.unitOfMeasureCode -eq [string]$p.unitOfMeasureCode -and [decimal]$line.unitPrice -eq [decimal]$p.unitPrice)
            $locationMatchesPriorInvoice = ([string]$line.locationCode -eq [string]$p.locationCode)
            $fullContextMatch = ($carriedFieldsMatch -and $locationMatchesPriorInvoice)
'@.TrimEnd("`r","`n")

$old2 = '            currentLineMatchesPriorRollingState = $matches'
$new2 = @'
            carriedQtyUomPriceMatchesPriorRollingState = $carriedFieldsMatch
            locationMatchesPriorPostedInvoice = $locationMatchesPriorInvoice
            fullQtyUomPriceLocationContextMatch = $fullContextMatch
'@.TrimEnd("`r","`n")

$old3 = @'
    $matching=@($comparisons | Where-Object { $_.currentLineMatchesPriorRollingState -eq $true })
    $unmodifiedMatching=@($comparisons | Where-Object { $_.currentLineMatchesPriorRollingState -eq $true -and $_.modifiedAfterCreation -eq $false })
'@
$new3 = @'
    $matching=@($comparisons | Where-Object { $_.carriedQtyUomPriceMatchesPriorRollingState -eq $true })
    $unmodifiedMatching=@($comparisons | Where-Object { $_.carriedQtyUomPriceMatchesPriorRollingState -eq $true -and $_.modifiedAfterCreation -eq $false })
    $locationMatching=@($comparisons | Where-Object { $_.locationMatchesPriorPostedInvoice -eq $true })
    $fullContextMatching=@($comparisons | Where-Object { $_.fullQtyUomPriceLocationContextMatch -eq $true })
'@

$old4 = @'
        matchingPriorRollingStateCount=$matching.Length
        unmodifiedMatchingPriorRollingStateCount=$unmodifiedMatching.Length
        comparisons=@($comparisons)
        interpretation='A match means the current Sales Line quantity/UOM/price/location equals the last qualifying posted invoice state that existed when the Sales Line was created. modifiedAfterCreation=true means later edits remain possible, so current values are not guaranteed to be original insert values.'
'@
$new4 = @'
        carriedQtyUomPriceMatchingPriorRollingStateCount=$matching.Length
        unmodifiedCarriedQtyUomPriceMatchingPriorRollingStateCount=$unmodifiedMatching.Length
        locationMatchingPriorPostedInvoiceCount=$locationMatching.Length
        fullQtyUomPriceLocationContextMatchCount=$fullContextMatching.Length
        comparisons=@($comparisons)
        interpretation='Boyer Customer Item Sales List carries Item No., Last Sold UOM, Last Sold Quantity and Last Unit Price. Its location assignment is commented out, so the primary carry-forward test is Qty+UOM+Unit Price. Location is reported separately as historical/context correlation. modifiedAfterCreation=true means later edits remain possible, so current values are not guaranteed to be original insert values.'
'@

$targets = @(
    [pscustomobject]@{Old=$old1;New=$new1;Name='carried field comparison'},
    [pscustomobject]@{Old=$old2;New=$new2;Name='comparison output fields'},
    [pscustomobject]@{Old=$old3.TrimEnd("`r","`n");New=$new3.TrimEnd("`r","`n");Name='summary match sets'},
    [pscustomobject]@{Old=$old4.TrimEnd("`r","`n");New=$new4.TrimEnd("`r","`n");Name='summary output and interpretation'}
)

$patched = $raw
foreach ($target in $targets) {
    $count = ([regex]::Matches($patched,[regex]::Escape([string]$target.Old))).Count
    if ($count -ne 1) { throw "Expected exactly one $($target.Name) patch target; found $count." }
    $patched = $patched.Replace([string]$target.Old,[string]$target.New)
}

$tempScript = Join-Path ([IO.Path]::GetTempPath()) ('GPIOrderIntake-OrderCreationVsBoyer-REV2-' + [guid]::NewGuid().ToString('N') + '.ps1')
try {
    Set-Content -LiteralPath $tempScript -Value $patched -Encoding UTF8 -NoNewline
    Write-Host 'REV2 carried-field patch : PASS' -ForegroundColor Green
    Write-Host 'Starting guarded diagnostic...' -ForegroundColor Cyan
    Write-Host ''
    & $tempScript
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "Patched diagnostic exited with code $LASTEXITCODE." }
}
finally {
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'GPI ORDER INTAKE ORDER CREATION VS BOYER REV2: WRAPPER COMPLETE' -ForegroundColor Green
