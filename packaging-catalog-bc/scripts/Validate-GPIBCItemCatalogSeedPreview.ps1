[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DiscoveryFolder
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$eligiblePath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_AutoSeed_Eligible.csv'
$previewPath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Seed_Preview.csv'

if (-not (Test-Path -LiteralPath $eligiblePath)) {
    throw "Auto-seed preview file was not found: $eligiblePath"
}
if (-not (Test-Path -LiteralPath $previewPath)) {
    throw "Seed preview file was not found: $previewPath"
}

$eligible = @(Import-Csv -LiteralPath $eligiblePath)
$preview = @(Import-Csv -LiteralPath $previewPath)

if ($eligible.Count -eq 0) {
    throw 'The auto-seed eligible file contains no records.'
}

function Get-OverLengthRows {
    param(
        [object[]]$Rows,
        [string]$Property,
        [int]$MaxLength
    )

    @(
        $Rows |
            Where-Object { ([string]$_.PSObject.Properties[$Property].Value).Length -gt $MaxLength } |
            ForEach-Object {
                [pscustomobject]@{
                    GamerID = $_.GamerID
                    Category = $_.ItemCategoryCode
                    Field = $Property
                    Length = ([string]$_.PSObject.Properties[$Property].Value).Length
                    MaxLength = $MaxLength
                    Value = [string]$_.PSObject.Properties[$Property].Value
                }
            }
    )
}

$duplicateGamerIds = @(
    $eligible |
        Group-Object GamerID |
        Where-Object { $_.Count -gt 1 } |
        ForEach-Object {
            [pscustomobject]@{ GamerID = $_.Name; Count = $_.Count }
        }
)

$duplicateBcItems = @(
    $eligible |
        Group-Object BCItemNo |
        Where-Object { $_.Count -gt 1 } |
        ForEach-Object {
            [pscustomobject]@{ BCItemNo = $_.Name; Count = $_.Count }
        }
)

$missingVendor = @($eligible | Where-Object { [string]::IsNullOrWhiteSpace([string]$_.VendorNo) })
$nonPositiveCost = @($eligible | Where-Object { [decimal]$_.CurrentSupplierUnitCost -le 0 })
$nonEaBaseUom = @($eligible | Where-Object { ([string]$_.BaseUnitOfMeasure).Trim().ToUpperInvariant() -ne 'EA' })

$fieldLengthChecks = @(
    @{ Name = 'GamerID'; Max = 20 },
    @{ Name = 'BCItemNo'; Max = 20 },
    @{ Name = 'SupplierMoldNo'; Max = 50 },
    @{ Name = 'Material'; Max = 30 },
    @{ Name = 'CapacityUOM'; Max = 10 },
    @{ Name = 'Finish'; Max = 50 },
    @{ Name = 'FinishType'; Max = 30 },
    @{ Name = 'Color'; Max = 30 },
    @{ Name = 'Style'; Max = 50 },
    @{ Name = 'Packout'; Max = 100 },
    @{ Name = 'VendorNo'; Max = 20 }
)

$overLength = [System.Collections.Generic.List[object]]::new()
foreach ($check in $fieldLengthChecks) {
    foreach ($row in @(Get-OverLengthRows -Rows $eligible -Property $check.Name -MaxLength $check.Max)) {
        $overLength.Add($row) | Out-Null
    }
}

$uomSummary = @(
    $eligible |
        Group-Object BaseUnitOfMeasure |
        ForEach-Object {
            [pscustomobject]@{
                BaseUnitOfMeasure = $(if ([string]::IsNullOrWhiteSpace($_.Name)) { '<blank>' } else { $_.Name })
                Count = $_.Count
                Categories = (($_.Group.ItemCategoryCode | Sort-Object -Unique) -join ', ')
            }
        } |
        Sort-Object Count -Descending
)

$categorySummary = @(
    $eligible |
        Group-Object ItemCategoryCode |
        ForEach-Object {
            $group = @($_.Group)
            [pscustomobject]@{
                Category = $_.Name
                Eligible = $group.Count
                BaseUomEA = @($group | Where-Object { ([string]$_.BaseUnitOfMeasure).Trim().ToUpperInvariant() -eq 'EA' }).Count
                NonEA = @($group | Where-Object { ([string]$_.BaseUnitOfMeasure).Trim().ToUpperInvariant() -ne 'EA' }).Count
                WithSupplierMoldNo = @($group | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.SupplierMoldNo) }).Count
                WithGramWeight = @($group | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_.GramWeight) -and [decimal]$_.GramWeight -gt 0 }).Count
                MinCost = ($group | ForEach-Object { [decimal]$_.CurrentSupplierUnitCost } | Measure-Object -Minimum).Minimum
                MaxCost = ($group | ForEach-Object { [decimal]$_.CurrentSupplierUnitCost } | Measure-Object -Maximum).Maximum
            }
        } |
        Sort-Object Eligible -Descending
)

$validationRows = [System.Collections.Generic.List[object]]::new()
foreach ($row in $eligible) {
    $issues = [System.Collections.Generic.List[string]]::new()

    if (([string]$row.BaseUnitOfMeasure).Trim().ToUpperInvariant() -ne 'EA') {
        $issues.Add('Base UOM is not EA; Last Direct Cost may not represent per-each supplier cost')
    }
    if ([string]::IsNullOrWhiteSpace([string]$row.VendorNo)) {
        $issues.Add('Missing Vendor No.')
    }
    if ([decimal]$row.CurrentSupplierUnitCost -le 0) {
        $issues.Add('Current Supplier Unit Cost is not positive')
    }
    if (@($overLength | Where-Object { $_.GamerID -eq $row.GamerID }).Count -gt 0) {
        $issues.Add('One or more values exceed GPI Packaging Product field length')
    }

    $validationRows.Add([pscustomobject]@{
        SafeForPilotSeed = ($issues.Count -eq 0)
        GamerID = $row.GamerID
        ItemCategoryCode = $row.ItemCategoryCode
        BaseUnitOfMeasure = $row.BaseUnitOfMeasure
        VendorNo = $row.VendorNo
        CurrentSupplierUnitCost = $row.CurrentSupplierUnitCost
        Material = $row.Material
        Capacity = $row.Capacity
        CapacityUOM = $row.CapacityUOM
        Finish = $row.Finish
        FinishType = $row.FinishType
        Color = $row.Color
        Style = $row.Style
        Issues = ($issues -join '; ')
    }) | Out-Null
}

$safeRows = @($validationRows | Where-Object { $_.SafeForPilotSeed })
$unsafeRows = @($validationRows | Where-Object { -not $_.SafeForPilotSeed })

$validationCsv = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Seed_Safety_Validation.csv'
$safeCsv = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Pilot_Seed_Eligible.csv'
$unsafeCsv = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Pilot_Seed_Hold.csv'
$overLengthCsv = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Field_Length_Issues.csv'

$validationRows | Export-Csv -LiteralPath $validationCsv -NoTypeInformation -Encoding UTF8
$safeRows | Export-Csv -LiteralPath $safeCsv -NoTypeInformation -Encoding UTF8
$unsafeRows | Export-Csv -LiteralPath $unsafeCsv -NoTypeInformation -Encoding UTF8
$overLength | Export-Csv -LiteralPath $overLengthCsv -NoTypeInformation -Encoding UTF8

Write-Host ''
Write-Host 'GPI PACKAGING CATALOG SEED SAFETY VALIDATION' -ForegroundColor Cyan
Write-Host "Discovery folder       : $DiscoveryFolder"
Write-Host "Auto-seed eligible     : $($eligible.Count)"
Write-Host "Safe for pilot seed    : $($safeRows.Count)"
Write-Host "Held for review        : $($unsafeRows.Count)"
Write-Host "Duplicate Gamer IDs    : $($duplicateGamerIds.Count)"
Write-Host "Duplicate BC Item Nos. : $($duplicateBcItems.Count)"
Write-Host "Missing Vendor No.     : $($missingVendor.Count)"
Write-Host "Non-positive cost      : $($nonPositiveCost.Count)"
Write-Host "Non-EA base UOM        : $($nonEaBaseUom.Count)"
Write-Host "Field length issues    : $($overLength.Count)"
Write-Host ''

Write-Host 'BASE UOM SUMMARY' -ForegroundColor Cyan
$uomSummary | Format-Table -AutoSize -Wrap

Write-Host ''
Write-Host 'CATEGORY SAFETY SUMMARY' -ForegroundColor Cyan
$categorySummary | Format-Table -AutoSize

if ($nonEaBaseUom.Count -gt 0) {
    Write-Host ''
    Write-Host 'SAMPLE NON-EA RECORDS' -ForegroundColor Yellow
    $nonEaBaseUom |
        Select-Object -First 20 ItemCategoryCode, GamerID, BaseUnitOfMeasure, VendorNo, CurrentSupplierUnitCost, Description |
        Format-Table -AutoSize -Wrap
}

if ($overLength.Count -gt 0) {
    Write-Host ''
    Write-Host 'SAMPLE FIELD LENGTH ISSUES' -ForegroundColor Yellow
    $overLength | Select-Object -First 20 GamerID, Category, Field, Length, MaxLength, Value | Format-Table -AutoSize -Wrap
}

Write-Host ''
Write-Host 'Created:' -ForegroundColor Green
Write-Host "  $validationCsv"
Write-Host "  $safeCsv"
Write-Host "  $unsafeCsv"
Write-Host "  $overLengthCsv"
Write-Host ''
Write-Host 'VALIDATION ONLY. No Business Central data was changed.'
