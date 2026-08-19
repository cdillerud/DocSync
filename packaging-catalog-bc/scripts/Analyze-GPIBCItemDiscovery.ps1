[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DiscoveryFolder,
    [int]$SamplesPerCategory = 20,
    [int]$ConsoleSamplesPerCategory = 4,
    [int]$TopCategoryCount = 15
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Convert-ToBoolean {
    param([AllowNull()]$Value)
    if ($null -eq $Value) { return $false }
    $text = ([string]$Value).Trim()
    return $text -match '^(?i:true|yes|1)$'
}

function Get-MatchValue {
    param(
        [string]$Text,
        [string]$Pattern
    )
    $match = [regex]::Match($Text, $Pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if ($match.Success) { return $match.Value }
    return ''
}

$itemsPath = Join-Path $DiscoveryFolder 'BC_Items.csv'
if (-not (Test-Path -LiteralPath $itemsPath)) {
    throw "BC_Items.csv was not found in $DiscoveryFolder"
}

$items = @(Import-Csv -LiteralPath $itemsPath)
if ($items.Count -eq 0) {
    throw 'BC_Items.csv contains no rows.'
}

$active = @(
    $items |
        Where-Object { -not (Convert-ToBoolean $_.Blocked) }
)

$categorySummary = @(
    $active |
        Group-Object ItemCategoryCode |
        ForEach-Object {
            $category = $_.Name
            if ([string]::IsNullOrWhiteSpace($category)) { $category = '<blank>' }

            $withDescription = @($_.Group | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Description) }).Count
            $withVendor = @($_.Group | Where-Object { -not [string]::IsNullOrWhiteSpace($_.VendorNo) }).Count
            $withVendorItem = @($_.Group | Where-Object { -not [string]::IsNullOrWhiteSpace($_.VendorItemNo) }).Count
            $withCost = @($_.Group | Where-Object { [decimal]$_.LastDirectCost -gt 0 }).Count

            [pscustomobject]@{
                ItemCategoryCode = $category
                ActiveCount = $_.Count
                WithDescription = $withDescription
                WithVendor = $withVendor
                WithVendorItemNo = $withVendorItem
                WithLastDirectCost = $withCost
            }
        } |
        Sort-Object ActiveCount -Descending
)

$topCategories = @($categorySummary | Select-Object -First $TopCategoryCount)
$sampleRows = [System.Collections.Generic.List[object]]::new()
$patternRows = [System.Collections.Generic.List[object]]::new()

$capacityPattern = '\b\d+(?:\.\d+)?\s*(?:OZ|FL\.?\s*OZ|ML|CL|L|LTR|LITER|GAL|GALLON|CC)\b'
$finishPattern = '\b\d{2,3}-\d{2,4}\b'
$packPattern = '\b\d+\s*(?:PK|PACK|CT|COUNT|CS|CASE|PC|PCS)\b|\b\d+\s*/\s*(?:CS|CASE|PK|PACK)\b'

$materialTokens = @('GLASS','PET','HDPE','LDPE','PP','POLYPROPYLENE','ALUMINUM','ALUMINIUM','STEEL','TIN','PAPER','PAPERBOARD','CORRUGATED','PLASTIC')
$colorTokens = @('FLINT','CLEAR','AMBER','WHITE','BLACK','GREEN','BLUE','NATURAL','RED','SILVER','GOLD','BROWN')

foreach ($categoryRow in $topCategories) {
    $category = [string]$categoryRow.ItemCategoryCode
    $categoryItems = @(
        $active |
            Where-Object {
                $value = [string]$_.ItemCategoryCode
                if ([string]::IsNullOrWhiteSpace($value)) { $value = '<blank>' }
                $value -eq $category
            } |
            Sort-Object ItemNo
    )

    foreach ($item in @($categoryItems | Select-Object -First $SamplesPerCategory)) {
        $sampleRows.Add([pscustomobject]@{
            ItemCategoryCode = $category
            ItemNo = $item.ItemNo
            Description = $item.Description
            Description2 = $item.Description2
            BaseUnitOfMeasure = $item.BaseUnitOfMeasure
            VendorNo = $item.VendorNo
            VendorItemNo = $item.VendorItemNo
            LastDirectCost = $item.LastDirectCost
        }) | Out-Null
    }

    $capacityCount = 0
    $finishCount = 0
    $packCount = 0
    $materialCount = 0
    $colorCount = 0
    $descriptionCount = 0
    $capacityExamples = [System.Collections.Generic.List[string]]::new()
    $finishExamples = [System.Collections.Generic.List[string]]::new()
    $packExamples = [System.Collections.Generic.List[string]]::new()

    foreach ($item in $categoryItems) {
        $description = (([string]$item.Description) + ' ' + ([string]$item.Description2)).Trim()
        if ([string]::IsNullOrWhiteSpace($description)) { continue }
        $descriptionCount++

        $capacity = Get-MatchValue -Text $description -Pattern $capacityPattern
        if (-not [string]::IsNullOrWhiteSpace($capacity)) {
            $capacityCount++
            if ($capacityExamples.Count -lt 5 -and -not $capacityExamples.Contains($capacity)) { $capacityExamples.Add($capacity) }
        }

        $finish = Get-MatchValue -Text $description -Pattern $finishPattern
        if (-not [string]::IsNullOrWhiteSpace($finish)) {
            $finishCount++
            if ($finishExamples.Count -lt 5 -and -not $finishExamples.Contains($finish)) { $finishExamples.Add($finish) }
        }

        $pack = Get-MatchValue -Text $description -Pattern $packPattern
        if (-not [string]::IsNullOrWhiteSpace($pack)) {
            $packCount++
            if ($packExamples.Count -lt 5 -and -not $packExamples.Contains($pack)) { $packExamples.Add($pack) }
        }

        $upper = $description.ToUpperInvariant()
        if (@($materialTokens | Where-Object { $upper -match "(?<![A-Z0-9])$([regex]::Escape($_))(?![A-Z0-9])" }).Count -gt 0) { $materialCount++ }
        if (@($colorTokens | Where-Object { $upper -match "(?<![A-Z0-9])$([regex]::Escape($_))(?![A-Z0-9])" }).Count -gt 0) { $colorCount++ }
    }

    $patternRows.Add([pscustomobject]@{
        ItemCategoryCode = $category
        ActiveCount = $categoryItems.Count
        DescriptionCount = $descriptionCount
        CapacityPatternCount = $capacityCount
        CapacityCoveragePct = $(if ($descriptionCount) { [math]::Round(($capacityCount / $descriptionCount) * 100, 2) } else { 0 })
        CapacityExamples = ($capacityExamples -join ' | ')
        FinishPatternCount = $finishCount
        FinishCoveragePct = $(if ($descriptionCount) { [math]::Round(($finishCount / $descriptionCount) * 100, 2) } else { 0 })
        FinishExamples = ($finishExamples -join ' | ')
        PackPatternCount = $packCount
        PackCoveragePct = $(if ($descriptionCount) { [math]::Round(($packCount / $descriptionCount) * 100, 2) } else { 0 })
        PackExamples = ($packExamples -join ' | ')
        MaterialTokenCount = $materialCount
        MaterialCoveragePct = $(if ($descriptionCount) { [math]::Round(($materialCount / $descriptionCount) * 100, 2) } else { 0 })
        ColorTokenCount = $colorCount
        ColorCoveragePct = $(if ($descriptionCount) { [math]::Round(($colorCount / $descriptionCount) * 100, 2) } else { 0 })
    }) | Out-Null
}

$sampleCsv = Join-Path $DiscoveryFolder 'BC_Active_Item_Description_Samples.csv'
$patternCsv = Join-Path $DiscoveryFolder 'BC_Description_Pattern_Coverage.csv'
$categoryCsv = Join-Path $DiscoveryFolder 'BC_Active_Category_Profile.csv'

$sampleRows | Export-Csv -LiteralPath $sampleCsv -NoTypeInformation -Encoding UTF8
$patternRows | Export-Csv -LiteralPath $patternCsv -NoTypeInformation -Encoding UTF8
$categorySummary | Export-Csv -LiteralPath $categoryCsv -NoTypeInformation -Encoding UTF8

Write-Host ''
Write-Host 'GPI BC ITEM DESCRIPTION ANALYSIS' -ForegroundColor Cyan
Write-Host "Discovery folder : $DiscoveryFolder"
Write-Host "Active items     : $($active.Count)"
Write-Host ''

Write-Host 'DESCRIPTION PATTERN COVERAGE' -ForegroundColor Cyan
$patternRows |
    Select-Object ItemCategoryCode, ActiveCount, CapacityCoveragePct, FinishCoveragePct, PackCoveragePct, MaterialCoveragePct, ColorCoveragePct |
    Format-Table -AutoSize

Write-Host ''
Write-Host 'SAMPLE ACTIVE ITEMS' -ForegroundColor Cyan
foreach ($categoryRow in $topCategories) {
    $category = [string]$categoryRow.ItemCategoryCode
    Write-Host ''
    Write-Host "[$category]" -ForegroundColor Yellow
    $sampleRows |
        Where-Object { $_.ItemCategoryCode -eq $category } |
        Select-Object -First $ConsoleSamplesPerCategory ItemNo, Description, BaseUnitOfMeasure, VendorNo, VendorItemNo, LastDirectCost |
        Format-Table -AutoSize -Wrap
}

Write-Host ''
Write-Host 'Created:' -ForegroundColor Green
Write-Host "  $sampleCsv"
Write-Host "  $patternCsv"
Write-Host "  $categoryCsv"
Write-Host ''
Write-Host 'No Business Central data was changed.'
