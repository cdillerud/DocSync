[CmdletBinding()]
param(
    [Parameter()]
    [string]$AppPath = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ScriptFile = $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($ScriptFile)) {
    throw 'Could not resolve the V69 federation preflight script path.'
}
$ScriptDirectory = Split-Path -Parent ([System.IO.Path]::GetFullPath($ScriptFile))
if ([string]::IsNullOrWhiteSpace($AppPath)) {
    $AppPath = Split-Path -Parent $ScriptDirectory
}

function Write-Section {
    param([Parameter(Mandatory)][string]$Title)
    Write-Host ''
    Write-Host ('=' * 118) -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ('=' * 118) -ForegroundColor Cyan
}

function Require-Text {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Needle,
        [Parameter(Mandatory)][string]$Label
    )
    if (-not $Text.Contains($Needle)) {
        throw "$Label is missing required contract text: $Needle"
    }
}

$AppPath = [System.IO.Path]::GetFullPath($AppPath)
$AppJsonPath = Join-Path $AppPath 'app.json'
$ProductApiPath = Join-Path $AppPath 'src\Pages\GPICommercialProductAPI.Page.al'
$VendorApiPath = Join-Path $AppPath 'src\Pages\GPICommercialVendorLocationAPI.Page.al'
$QuoteApiPath = Join-Path $AppPath 'src\Pages\GPIQuoteSummaryAPI.Page.al'
$CompareApiPath = Join-Path $AppPath 'src\Pages\GPICompareLineAPI.Page.al'
$ProductTablePath = Join-Path $AppPath 'src\Tables\GPIPackagingProduct.Table.al'
$PermissionPath = Join-Path $AppPath 'src\PermissionSets\GPIV69Federation.PermissionSetExt.al'
$BuildPath = Join-Path $AppPath 'scripts\Build-GPIPackagingCatalog.ps1'

Write-Host ''
Write-Host ('=' * 118) -ForegroundColor Cyan
Write-Host 'GPI PACKAGING CATALOG V69 COMMERCIAL CONTEXT FEDERATION / LOCAL PREFLIGHT' -ForegroundColor Cyan
Write-Host ('=' * 118) -ForegroundColor Cyan
Write-Host "Resolved app path               : $AppPath"
Write-Host 'Business Central calls          : NONE'
Write-Host 'Business Central writes         : NONE'
Write-Host 'Publish/install                 : NONE'
Write-Host 'Production touched              : NO'
Write-Host 'Secrets output                  : NO'

Write-Section '1. REQUIRED SOURCE FILES'
foreach ($Path in @($AppJsonPath, $ProductApiPath, $VendorApiPath, $QuoteApiPath, $CompareApiPath, $ProductTablePath, $PermissionPath, $BuildPath)) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required source file is missing: $Path"
    }
}
Write-Host 'Required source files           : PASS'

Write-Section '2. APP VERSION / UAT BUILD CONTRACT'
$AppJson = Get-Content -LiteralPath $AppJsonPath -Raw | ConvertFrom-Json
Write-Host "App version                     : $($AppJson.version)"
if ([string]$AppJson.version -ne '0.48.0.0') {
    throw 'V69 federation preflight requires GPI Packaging Catalog version 0.48.0.0.'
}

Write-Section '3. READ-ONLY COMMERCIAL PRODUCT API'
$ProductApi = Get-Content -LiteralPath $ProductApiPath -Raw
foreach ($Needle in @(
    "APIGroup = 'commercialAgents';",
    "EntitySetName = 'commercialProducts';",
    'InsertAllowed = false;',
    'ModifyAllowed = false;',
    'DeleteAllowed = false;',
    'field(bcItemDescription; Rec."BC Item Description")',
    'field(vendorName; Rec."Vendor Name")',
    'field(fobCity; Rec."FOB City")',
    'field(fobStateProvince; Rec."FOB State/Province")',
    'field(fullLoadQuantity; Rec."Full Load Quantity")',
    'field(currentSupplierUnitCost; Rec."Current Supplier Unit Cost")',
    'field(metricTonCost; Rec."Metric Ton Cost")',
    'field(drawingFileName; Rec."Drawing File Name")'
)) {
    Require-Text -Text $ProductApi -Needle $Needle -Label 'commercialProducts API'
}
Write-Host 'commercialProducts              : PASS / READ ONLY / EXPANDED CONTEXT'

Write-Section '4. READ-ONLY COMMERCIAL VENDOR LOCATION API'
$VendorApi = Get-Content -LiteralPath $VendorApiPath -Raw
foreach ($Needle in @(
    'page 71127 "GPI Comm Vendor Loc API"',
    "APIGroup = 'commercialAgents';",
    "EntitySetName = 'commercialVendorLocations';",
    'InsertAllowed = false;',
    'ModifyAllowed = false;',
    'DeleteAllowed = false;',
    'field(countryRegionCode; Rec."Country/Region Code")',
    'field(latitude; Rec.Latitude)',
    'field(longitude; Rec.Longitude)'
)) {
    Require-Text -Text $VendorApi -Needle $Needle -Label 'commercialVendorLocations API'
}
$Permission = Get-Content -LiteralPath $PermissionPath -Raw
Require-Text -Text $Permission -Needle 'page "GPI Comm Vendor Loc API" = X;' -Label 'V69 permission set extension'
Write-Host 'commercialVendorLocations       : PASS / READ ONLY / COUNTRY + GEO CONTEXT'

Write-Section '5. EXISTING QUOTE + SOURCING-COMPARISON AUTHORITY'
$QuoteApi = Get-Content -LiteralPath $QuoteApiPath -Raw
foreach ($Needle in @(
    "EntitySetName = 'packagingQuoteSummaries';",
    'InsertAllowed = false;',
    'ModifyAllowed = false;',
    'DeleteAllowed = false;',
    'field(totalLandedCost; Rec."Total Landed Cost")',
    'field(grossMarginPct; GrossMarginPct)',
    'field(spiroOpportunityId; Rec."GPI Spiro Opportunity ID")',
    'field(recommendedNextAction; RecommendedNextAction)'
)) {
    Require-Text -Text $QuoteApi -Needle $Needle -Label 'packagingQuoteSummaries API'
}
$CompareApi = Get-Content -LiteralPath $CompareApiPath -Raw
foreach ($Needle in @(
    "EntitySetName = 'packagingComparisonLines';",
    'field(supplierUnitCost; Rec."Supplier Unit Cost")',
    'field(tariffPct; Rec."Tariff %")',
    'field(freightBasis; Rec."Freight Basis")',
    'field(landedCostPerUnit; Rec."Landed Cost per Unit")',
    'field(suggestedSellPrice; Rec."Suggested Sell Price")',
    'field(rank; Rec.Rank)'
)) {
    Require-Text -Text $CompareApi -Needle $Needle -Label 'packagingComparisonLines API'
}
Write-Host 'packagingQuoteSummaries         : PASS / READ ONLY'
Write-Host 'packagingComparisonLines        : PRESENT / V69 CONSUMER GET-ONLY'

Write-Section '6. RFQ MASTERBOOK MIGRATION GAPS / DO NOT INVENT'
$ProductTable = Get-Content -LiteralPath $ProductTablePath -Raw
$HasMoq = $ProductTable -match '(?i)\bMOQ\b'
$HasIncoterm = $ProductTable -match '(?i)Incoterm'
Write-Host "Authoritative MOQ field         : $HasMoq"
Write-Host "Authoritative Incoterm field    : $HasIncoterm"
if ($HasMoq -or $HasIncoterm) {
    throw 'Expected MOQ/Incoterm migration gaps changed. Review V69 authority mapping before proceeding.'
}
Write-Host 'MOQ gap                         : CONFIRMED / SOURCE TEXT MUST BE PRESERVED' -ForegroundColor Yellow
Write-Host 'Incoterm gap                    : CONFIRMED / SOURCE TEXT MUST BE PRESERVED' -ForegroundColor Yellow

Write-Section '7. COMPILE GPI PACKAGING CATALOG / NO PUBLISH'
& $BuildPath -AppPath $AppPath
if ($LASTEXITCODE -ne 0) {
    throw "GPI Packaging Catalog build failed with exit code $LASTEXITCODE"
}

Write-Section '8. FINAL BC FEDERATION PREFLIGHT RESULT'
Write-Host 'GPI Packaging Catalog           : PASS / 0.48.0.0' -ForegroundColor Green
Write-Host 'Commercial product context      : PASS / READ ONLY' -ForegroundColor Green
Write-Host 'Vendor/FOB country context      : PASS / READ ONLY' -ForegroundColor Green
Write-Host 'Quote summary context           : PASS / READ ONLY' -ForegroundColor Green
Write-Host 'Saved sourcing comparison       : PRESENT' -ForegroundColor Green
Write-Host 'MOQ                             : MIGRATION GAP / NOT INVENTED' -ForegroundColor Yellow
Write-Host 'Incoterm                        : MIGRATION GAP / NOT INVENTED' -ForegroundColor Yellow
Write-Host 'Business Central calls          : NONE'
Write-Host 'Business Central writes         : NONE'
Write-Host 'Publish/install                 : NONE'
Write-Host 'Production touched              : NO'
Write-Host 'Secrets output                  : NO'
Write-Host ''
Write-Host ('=' * 118) -ForegroundColor Green
Write-Host 'GPI PACKAGING CATALOG V69 COMMERCIAL FEDERATION PREFLIGHT PASSED' -ForegroundColor Green
Write-Host ('=' * 118) -ForegroundColor Green
