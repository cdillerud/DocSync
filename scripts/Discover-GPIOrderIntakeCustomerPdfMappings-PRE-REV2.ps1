#requires -Version 7.0

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$BasePath = Join-Path $PSScriptRoot 'Discover-GPIOrderIntakeCustomerPdfMappings-PRE.ps1'
$ExpectedBaseBlob = '3fbc8ca3ea8f9a5dfe0feeff00030594ad5eb451'

if (-not (Test-Path -LiteralPath $BasePath -PathType Leaf)) {
    throw "Committed customer-PDF discovery base script not found: $BasePath"
}

$actualBlob = (& git hash-object -- $BasePath).Trim()
if ($LASTEXITCODE -ne 0) { throw 'git hash-object failed while validating customer-PDF discovery base script.' }
if ($actualBlob -ne $ExpectedBaseBlob) {
    throw "Unexpected customer-PDF discovery base blob: $actualBlob"
}

$source = Get-Content -LiteralPath $BasePath -Raw

$herdezAnchor = @'
$Herdez = [ordered]@{
    CustomerName         = 'Herdez'
    CustomerPo           = '4500063632'
'@
$herdezReplacement = @'
$Herdez = [ordered]@{
    CustomerName         = 'Herdez'
    CustomerNo           = 'HERDEZ'
    CustomerPo           = '4500063632'
'@
$herdezAnchorCount = ([regex]::Matches($source, [regex]::Escape($herdezAnchor))).Count
Write-Host "Patch target exact Herdez customer key : $herdezAnchorCount / 1"
if ($herdezAnchorCount -ne 1) { throw "Expected one Herdez customer-key patch target; found $herdezAnchorCount." }
$source = $source.Replace($herdezAnchor, $herdezReplacement)

$historyOld = 'return @(Invoke-BcGetAll "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$filter&`$top=200" $headers)'
$historyNew = 'return @(Invoke-BcGetAll "$customRoot/orderIntakeSalesInvoiceLineHistories?`$filter=$filter" $headers)'
$historyCount = ([regex]::Matches($source, [regex]::Escape($historyOld))).Count
Write-Host "Patch target uncapped posted history     : $historyCount / 1"
if ($historyCount -ne 1) { throw "Expected one posted-history cap patch target; found $historyCount." }
$source = $source.Replace($historyOld, $historyNew)

$customerOld = @'
$allCustomers = @(Invoke-BcGetAll "$companyRoot/customers?`$select=$customerSelect&`$top=200" $headers)
$herdezCustomers = @($allCustomers | Where-Object {
    (Normalize-Key ([string]$_.displayName)).Contains('HERDEZ') -or (Normalize-Key ([string]$_.number)).Contains('HERDEZ')
})
Write-Host ''
Write-Host 'HERDEZ_CUSTOMER_DISCOVERY' -ForegroundColor Cyan
foreach ($c in $herdezCustomers) {
    Write-Host ('CUSTOMER_MATCH|label=HERDEZ|number={0}|matches={1}|name={2}|city={3}|state={4}|blocked={5}' -f $c.number,$herdezCustomers.Count,$c.displayName,$c.city,$c.state,$c.blocked)
}
if ($herdezCustomers.Count -eq 0) { Write-Host 'CUSTOMER_MATCH|label=HERDEZ|matches=0' }
'@
$customerNew = @'
$herdezCustomers = @(Get-CustomerByNumber $Herdez.CustomerNo)
Write-Host ''
Write-Host 'HERDEZ_CUSTOMER_DISCOVERY' -ForegroundColor Cyan
foreach ($c in $herdezCustomers) {
    Write-Host ('CUSTOMER_MATCH|label=HERDEZ|number={0}|matches={1}|name={2}|city={3}|state={4}|blocked={5}' -f $c.number,$herdezCustomers.Count,$c.displayName,$c.city,$c.state,$c.blocked)
}
if ($herdezCustomers.Count -eq 0) { Write-Host "CUSTOMER_MATCH|label=HERDEZ|number=$($Herdez.CustomerNo)|matches=0" }
'@
$customerCount = ([regex]::Matches($source, [regex]::Escape($customerOld))).Count
Write-Host "Patch target exact Herdez customer probe: $customerCount / 1"
if ($customerCount -ne 1) { throw "Expected one Herdez customer-discovery patch target; found $customerCount." }
$source = $source.Replace($customerOld, $customerNew)

$titleOld = 'GPI ORDER INTAKE - CUSTOMER PDF MAPPING DISCOVERY / PRE GET ONLY'
$titleNew = 'GPI ORDER INTAKE - CUSTOMER PDF MAPPING DISCOVERY REV2 / PRE GET ONLY'
$titleCount = ([regex]::Matches($source, [regex]::Escape($titleOld))).Count
Write-Host "Patch target REV2 title                 : $titleCount / 1"
if ($titleCount -ne 1) { throw "Expected one discovery title patch target; found $titleCount." }
$source = $source.Replace($titleOld, $titleNew)

$tempPath = Join-Path $PSScriptRoot ('.GPIOrderIntake-CustomerPdfMappings-REV2-{0}.tmp.ps1' -f ([guid]::NewGuid().ToString('N')))

Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host 'GPI ORDER INTAKE - CUSTOMER PDF MAPPING DISCOVERY REV2 / EVIDENCE HARDENING' -ForegroundColor Cyan
Write-Host ('=' * 120) -ForegroundColor Cyan
Write-Host "Committed base blob : $ExpectedBaseBlob"
Write-Host 'Correction 1        : exact BC customer-number probe HERDEZ; no bounded fuzzy customer scan'
Write-Host 'Correction 2        : posted Sales Invoice Line history queried without a $top total-result cap'
Write-Host 'Business logic      : source quantity remains evidence; BC quantity still requires proven mapping'
Write-Host 'HTTP methods        : GET ONLY' -ForegroundColor Green
Write-Host 'Extension mutation  : NONE' -ForegroundColor Green
Write-Host 'Business data write : NONE' -ForegroundColor Green
Write-Host 'Sales-order action  : NOT CALLED' -ForegroundColor Green
Write-Host 'Production          : HARD BLOCKED' -ForegroundColor Green
Write-Host ('=' * 120) -ForegroundColor Cyan

try {
    Set-Content -LiteralPath $tempPath -Value $source -Encoding utf8NoBOM
    & $tempPath
    if (-not $?) { throw 'Temporary customer-PDF discovery REV2 script failed.' }
}
finally {
    Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
}
