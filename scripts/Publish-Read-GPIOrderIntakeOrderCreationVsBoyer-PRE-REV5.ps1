#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedSourceBlob = '0a1abca753d926407b040cde6461d1fcf0570814'
$SourcePath = 'scripts/Publish-Read-GPIOrderIntakeOrderCreationVsBoyer-PRE.ps1'

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $RepoRoot
try {
    $HeadBlob = (& git rev-parse "HEAD:$SourcePath").Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not resolve committed source blob for $SourcePath." }
}
finally {
    Pop-Location
}

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - ORDER CREATION VS BOYER REV5 / GIT-OBJECT-SOURCE' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Expected committed blob : $ExpectedSourceBlob"
Write-Host "HEAD committed blob     : $HeadBlob"
if ($HeadBlob -ne $ExpectedSourceBlob) { throw 'Committed source blob verification failed.' }
Write-Host 'Committed blob verification: PASS' -ForegroundColor Green
Write-Host 'Working-tree source        : NOT READ / NOT MODIFIED'
Write-Host 'Endpoint fix               : orderIntakePostedInvoiceLines -> orderIntakeSalesInvoiceLineHistories'
Write-Host 'Comparison scope           : Qty + UOM + Unit Price are Boyer-carried fields; Location reported separately'
Write-Host 'Temp script root           : repository scripts folder (preserves PSScriptRoot)'
Write-Host 'Business data writes       : NONE'
Write-Host 'Sales-order action         : NOT CALLED'
Write-Host 'Production                 : HARD BLOCKED'
Write-Host ('=' * 120) -ForegroundColor Cyan

Push-Location $RepoRoot
try {
    $blobLines = @(& git cat-file -p $ExpectedSourceBlob)
    if ($LASTEXITCODE -ne 0) { throw 'Could not read committed source blob from Git object database.' }
}
finally {
    Pop-Location
}
$raw = ($blobLines -join "`n")

function Normalize-Lf {
    param([Parameter(Mandatory)][AllowEmptyString()][string]$Text)
    return $Text.Replace("`r`n", "`n").Replace("`r", "`n")
}

$oldEndpoint = '$invoiceUri = "$customRoot/orderIntakePostedInvoiceLines?`$filter=$filter&`$top=500"'
$newEndpoint = '$invoiceUri = "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$filter&`$top=500"'

$oldCompare = '            $matches = ([decimal]$line.quantity -eq [decimal]$p.quantity -and [string]$line.unitOfMeasureCode -eq [string]$p.unitOfMeasureCode -and [decimal]$line.unitPrice -eq [decimal]$p.unitPrice -and [string]$line.locationCode -eq [string]$p.locationCode)'
$newCompare = @'
            $carriedFieldsMatch = ([decimal]$line.quantity -eq [decimal]$p.quantity -and [string]$line.unitOfMeasureCode -eq [string]$p.unitOfMeasureCode -and [decimal]$line.unitPrice -eq [decimal]$p.unitPrice)
            $locationMatchesPriorInvoice = ([string]$line.locationCode -eq [string]$p.locationCode)
            $fullContextMatch = ($carriedFieldsMatch -and $locationMatchesPriorInvoice)
'@.TrimEnd("`r","`n")

$oldOutput = '            currentLineMatchesPriorRollingState = $matches'
$newOutput = @'
            carriedQtyUomPriceMatchesPriorRollingState = $carriedFieldsMatch
            locationMatchesPriorPostedInvoice = $locationMatchesPriorInvoice
            fullQtyUomPriceLocationContextMatch = $fullContextMatch
'@.TrimEnd("`r","`n")

$oldSets = @'
    $matching=@($comparisons | Where-Object { $_.currentLineMatchesPriorRollingState -eq $true })
    $unmodifiedMatching=@($comparisons | Where-Object { $_.currentLineMatchesPriorRollingState -eq $true -and $_.modifiedAfterCreation -eq $false })
'@.TrimEnd("`r","`n")
$newSets = @'
    $matching=@($comparisons | Where-Object { $_.carriedQtyUomPriceMatchesPriorRollingState -eq $true })
    $unmodifiedMatching=@($comparisons | Where-Object { $_.carriedQtyUomPriceMatchesPriorRollingState -eq $true -and $_.modifiedAfterCreation -eq $false })
    $locationMatching=@($comparisons | Where-Object { $_.locationMatchesPriorPostedInvoice -eq $true })
    $fullContextMatching=@($comparisons | Where-Object { $_.fullQtyUomPriceLocationContextMatch -eq $true })
'@.TrimEnd("`r","`n")

$oldSummary = @'
        matchingPriorRollingStateCount=$matching.Length
        unmodifiedMatchingPriorRollingStateCount=$unmodifiedMatching.Length
        comparisons=@($comparisons)
        interpretation='A match means the current Sales Line quantity/UOM/price/location equals the last qualifying posted invoice state that existed when the Sales Line was created. modifiedAfterCreation=true means later edits remain possible, so current values are not guaranteed to be original insert values.'
'@.TrimEnd("`r","`n")
$newSummary = @'
        carriedQtyUomPriceMatchingPriorRollingStateCount=$matching.Length
        unmodifiedCarriedQtyUomPriceMatchingPriorRollingStateCount=$unmodifiedMatching.Length
        locationMatchingPriorPostedInvoiceCount=$locationMatching.Length
        fullQtyUomPriceLocationContextMatchCount=$fullContextMatching.Length
        comparisons=@($comparisons)
        interpretation='Boyer Customer Item Sales List carries Item No., Last Sold UOM, Last Sold Quantity and Last Unit Price. Its location assignment is commented out, so the primary carry-forward test is Qty+UOM+Unit Price. Location is reported separately as historical/context correlation. modifiedAfterCreation=true means later edits remain possible, so current values are not guaranteed to be original insert values.'
'@.TrimEnd("`r","`n")

$patches = @(
    [pscustomobject]@{ Name='invoice history entity set'; Old=$oldEndpoint; New=$newEndpoint },
    [pscustomobject]@{ Name='carried field comparison'; Old=$oldCompare; New=$newCompare },
    [pscustomobject]@{ Name='comparison output fields'; Old=$oldOutput; New=$newOutput },
    [pscustomobject]@{ Name='summary match sets'; Old=$oldSets; New=$newSets },
    [pscustomobject]@{ Name='summary output'; Old=$oldSummary; New=$newSummary }
)

$patched = Normalize-Lf $raw
foreach ($patch in $patches) {
    $old = Normalize-Lf ([string]$patch.Old)
    $new = Normalize-Lf ([string]$patch.New)
    $count = ([regex]::Matches($patched, [regex]::Escape($old))).Count
    if ($count -ne 1) { throw "Expected exactly one $($patch.Name) patch target; found $count." }
    $patched = $patched.Replace($old, $new)
}

$tempScript = Join-Path $PSScriptRoot ('.GPIOrderIntake-OrderCreationVsBoyer-REV5-' + [guid]::NewGuid().ToString('N') + '.tmp.ps1')
try {
    Set-Content -LiteralPath $tempScript -Value $patched -Encoding UTF8 -NoNewline
    Write-Host 'REV5 committed-source patches: PASS' -ForegroundColor Green
    Write-Host 'Starting guarded diagnostic...' -ForegroundColor Cyan
    Write-Host ''
    & $tempScript
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "Patched diagnostic exited with code $LASTEXITCODE." }
}
finally {
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host 'GPI ORDER INTAKE ORDER CREATION VS BOYER REV5: WRAPPER COMPLETE' -ForegroundColor Green
