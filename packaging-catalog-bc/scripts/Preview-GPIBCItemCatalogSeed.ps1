[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$DiscoveryFolder
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Convert-ToBoolean {
    param([AllowNull()]$Value)
    if ($null -eq $Value) { return $false }
    return ([string]$Value).Trim() -match '^(?i:true|yes|1)$'
}

function Get-FirstRegexValue {
    param([string]$Text, [string]$Pattern)
    $m = [regex]::Match($Text, $Pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if ($m.Success) { return $m.Value.Trim() }
    return ''
}

function Get-FirstTokenMatch {
    param([string[]]$Tokens, [string[]]$Candidates)
    foreach ($token in $Tokens) {
        foreach ($candidate in $Candidates) {
            if ($token -match "(?i)(?<![A-Z0-9])$([regex]::Escape($candidate))(?![A-Z0-9])") {
                return $candidate
            }
        }
    }
    return ''
}

function Normalize-Capacity {
    param([string]$Text)

    $m = [regex]::Match(
        $Text,
        '(?i)\b(?<value>\d+(?:\.\d+)?)\s*(?<uom>FL\.?\s*OZ|OZ|ML|CL|LTR|LITER|L|GAL|GALLON|CC)\b'
    )
    if (-not $m.Success) {
        return [pscustomobject]@{ Value = ''; Uom = '' }
    }

    $uom = $m.Groups['uom'].Value.ToUpperInvariant().Replace('.', '').Replace(' ', '')
    switch ($uom) {
        'FLOZ'   { $uom = 'OZ' }
        'LTR'    { $uom = 'L' }
        'LITER'  { $uom = 'L' }
        'GALLON' { $uom = 'GAL' }
    }

    return [pscustomobject]@{
        Value = $m.Groups['value'].Value
        Uom = $uom
    }
}

function Normalize-Finish {
    param([string]$Category, [string[]]$Tokens, [string]$Description)

    $standardFinish = Get-FirstRegexValue -Text $Description -Pattern '\b\d{2,3}[-/]\d{2,4}\b'
    if ($standardFinish) { return $standardFinish.Replace('/', '-') }

    switch ($Category) {
        'CAN' {
            if ($Tokens.Count -ge 2 -and $Tokens[1] -match '^\d{3}$') { return $Tokens[1] }
        }
        'CAP' {
            if ($Tokens.Count -ge 1 -and $Tokens[0] -match '^\d{2,3}(?:mm)?(?:\s+.*)?$') { return $Tokens[0] }
        }
        'CANEND' {
            if ($Tokens.Count -ge 1 -and $Tokens[0] -match '^\d{3}$') { return $Tokens[0] }
        }
        'CROWN' {
            if ($Tokens.Count -ge 1 -and $Tokens[0] -match '^\d+(?:\.\d+)?mm$') { return $Tokens[0] }
        }
        'BARTOP' {
            if ($Tokens.Count -ge 1 -and $Tokens[0] -match '^\d+(?:\.\d+)?mm$') { return $Tokens[0] }
        }
        'PUMP' {
            $pumpFinish = Get-FirstRegexValue -Text $Description -Pattern '\b\d{2,3}[-/]\d{3}\b'
            if ($pumpFinish) { return $pumpFinish.Replace('/', '-') }
        }
    }

    return ''
}

function Get-GramWeight {
    param([string]$Description)
    $m = [regex]::Match($Description, '(?i)(?:^|[,\s])(?<value>\d+(?:\.\d+)?)\s*g\b')
    if ($m.Success) { return $m.Groups['value'].Value }
    return ''
}

function Get-Packout {
    param([string]$Description)
    return Get-FirstRegexValue -Text $Description -Pattern '\b\d+\s*(?:PK|PACK|CT|COUNT|CS|CASE|PC|PCS)\b|\b\d+\s*/\s*(?:CS|CASE|PK|PACK)\b'
}

function Get-Style {
    param([string]$Category, [string[]]$Tokens, [string]$Material, [string]$Color)

    switch ($Category) {
        'BOTTLE' { if ($Tokens.Count -ge 6) { return $Tokens[5] } }
        'JAR'    { if ($Tokens.Count -ge 6) { return $Tokens[5] } }
        'CAP'    { if ($Tokens.Count -ge 4) { return $Tokens[3] } }
        'CAN'    { if ($Tokens.Count -ge 3) { return $Tokens[2] } }
        'CANEND' { if ($Tokens.Count -ge 3) { return $Tokens[2] } }
        'CROWN'  { if ($Tokens.Count -ge 4) { return $Tokens[3] } }
        'BARTOP' { if ($Tokens.Count -ge 4) { return $Tokens[3] } }
        'PUMP' {
            $joined = $Tokens -join ', '
            foreach ($pattern in @('Fine Mist Sprayer','Mist Sprayer','HV Sprayer','Trigger Sprayer','Pump','Sprayer')) {
                if ($joined -match [regex]::Escape($pattern)) { return $pattern }
            }
        }
        'TUBE' { return 'Tube' }
        'CARRIER' { return 'Carrier' }
        'CARTON' { return 'Carton' }
        'FLEX' {
            if (($Tokens -join ' ') -match '(?i)shrink') { return 'Shrink Band' }
            return 'Flexible Packaging'
        }
    }

    return ''
}

function Get-FinishType {
    param([string]$Category, [string[]]$Tokens)
    switch ($Category) {
        'BOTTLE' { if ($Tokens.Count -ge 3) { return $Tokens[2] } }
        'JAR'    { if ($Tokens.Count -ge 3) { return $Tokens[2] } }
        'CAP'    { if ($Tokens.Count -ge 2) { return $Tokens[1] } }
        'CANEND' { if ($Tokens.Count -ge 2) { return $Tokens[1] } }
        'CROWN'  { if ($Tokens.Count -ge 2) { return $Tokens[1] } }
    }
    return ''
}

function Get-Color {
    param([string]$Category, [string[]]$Tokens)

    switch ($Category) {
        'BOTTLE' { if ($Tokens.Count -ge 4) { return $Tokens[3] } }
        'JAR'    { if ($Tokens.Count -ge 4) { return $Tokens[3] } }
        'CAP'    { if ($Tokens.Count -ge 5) { return $Tokens[4] } }
        'CANEND' { if ($Tokens.Count -ge 4) { return $Tokens[3] } }
        'CROWN'  { if ($Tokens.Count -ge 5) { return $Tokens[4] } }
        'BARTOP' { if ($Tokens.Count -ge 5) { return $Tokens[4] } }
    }

    $knownColors = @('Flint','Clear','Amber','White','Black','Green','Blue','Natural','Red','Silver','Gold','Brown','Brite','Yellow','Teal','Orange','Purple')
    foreach ($token in $Tokens) {
        foreach ($color in $knownColors) {
            if ($token -match "(?i)(?<![A-Z0-9])$([regex]::Escape($color))(?![A-Z0-9])") {
                return $token
            }
        }
    }
    return ''
}

function Get-Material {
    param([string[]]$Tokens)

    $materials = @(
        'Glass','PET','HDPE','LDPE','PP','Polypropylene','Alum','Aluminum','Aluminium',
        'Steel','TFS','Tin','PVC','Paper','Paperboard','Corrugated','Plastic','Wood','PE','EVOH','ABL'
    )

    foreach ($token in $Tokens) {
        foreach ($material in $materials) {
            if ($token -match "(?i)(?<![A-Z0-9])$([regex]::Escape($material))(?![A-Z0-9])") {
                switch -Regex ($material.ToUpperInvariant()) {
                    '^ALUM' { return 'Aluminum' }
                    '^POLYPROPYLENE$' { return 'PP' }
                    default { return $material.ToUpperInvariant() }
                }
            }
        }
    }
    return ''
}

function Get-Confidence {
    param(
        [string]$Category,
        [string]$VendorNo,
        [decimal]$LastDirectCost,
        [string]$Capacity,
        [string]$Finish,
        [string]$Material,
        [string]$Color,
        [string]$Style
    )

    $score = 0
    if ($VendorNo) { $score += 15 }
    if ($LastDirectCost -gt 0) { $score += 15 }
    if ($Capacity) { $score += 15 }
    if ($Finish) { $score += 15 }
    if ($Material) { $score += 15 }
    if ($Color) { $score += 10 }
    if ($Style) { $score += 10 }

    switch ($Category) {
        'CAP'    { if (-not $Capacity) { $score += 10 } }
        'CANEND' { if (-not $Capacity) { $score += 10 } }
        'CROWN'  { if (-not $Capacity) { $score += 10 } }
        'BARTOP' { if (-not $Capacity) { $score += 10 } }
        'PUMP'   { if (-not $Capacity) { $score += 5 } }
    }

    if ($score -gt 100) { $score = 100 }
    $label = if ($score -ge 75) { 'High' } elseif ($score -ge 50) { 'Medium' } else { 'Low' }

    return [pscustomobject]@{ Score = $score; Label = $label }
}

function Test-AutoSeedEligible {
    param(
        [string]$Category,
        [string]$VendorNo,
        [decimal]$LastDirectCost,
        [string]$Capacity,
        [string]$Finish,
        [string]$Material,
        [string]$Color
    )

    if (-not $VendorNo -or $LastDirectCost -le 0) { return $false }

    switch ($Category) {
        'BOTTLE' { return [bool]($Capacity -and $Finish -and $Material -and $Color) }
        'JAR'    { return [bool]($Capacity -and $Finish -and $Material -and $Color) }
        'CAN'    { return [bool]($Capacity -and $Finish -and $Material) }
        'CAP'    { return [bool]($Finish -and $Material -and $Color) }
        'CANEND' { return [bool]($Finish -and $Material -and $Color) }
        'CROWN'  { return [bool]($Finish -and $Material -and $Color) }
        'BARTOP' { return [bool]($Finish -and $Material -and $Color) }
        'TUBE'   { return [bool]($Capacity -and $Material) }
        'PUMP'   { return [bool]($Finish -and $Color) }
        default  { return $false }
    }
}

$itemsPath = Join-Path $DiscoveryFolder 'BC_Items.csv'
if (-not (Test-Path -LiteralPath $itemsPath)) {
    throw "BC_Items.csv was not found in $DiscoveryFolder"
}

$items = @(Import-Csv -LiteralPath $itemsPath)
$targetCategories = @('CAN','CAP','BOTTLE','JAR','TUBE','CARRIER','CANEND','CARTON','CROWN','FLEX','BARTOP','PUMP')

$candidates = [System.Collections.Generic.List[object]]::new()

foreach ($item in $items) {
    if (Convert-ToBoolean $item.Blocked) { continue }
    if (Convert-ToBoolean $item.PackagingCatalogMapped) { continue }

    $category = ([string]$item.ItemCategoryCode).Trim().ToUpperInvariant()
    if ($targetCategories -notcontains $category) { continue }

    $description = ((([string]$item.Description) + ' ' + ([string]$item.Description2)).Trim())
    if (-not $description) { continue }

    $tokens = @(
        $description -split ',' |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    )

    $capacity = Normalize-Capacity -Text $description
    if ($category -in @('CAP','CANEND','CROWN','BARTOP','PUMP')) {
        $capacity = [pscustomobject]@{ Value = ''; Uom = '' }
    }

    $finish = Normalize-Finish -Category $category -Tokens $tokens -Description $description
    $material = Get-Material -Tokens $tokens
    $color = Get-Color -Category $category -Tokens $tokens
    $style = Get-Style -Category $category -Tokens $tokens -Material $material -Color $color
    $finishType = Get-FinishType -Category $category -Tokens $tokens
    $packout = Get-Packout -Description $description
    $gramWeight = Get-GramWeight -Description $description
    $lastDirectCost = 0
    [void][decimal]::TryParse([string]$item.LastDirectCost, [ref]$lastDirectCost)

    $confidence = Get-Confidence -Category $category -VendorNo ([string]$item.VendorNo) -LastDirectCost $lastDirectCost -Capacity $capacity.Value -Finish $finish -Material $material -Color $color -Style $style
    $autoEligible = Test-AutoSeedEligible -Category $category -VendorNo ([string]$item.VendorNo) -LastDirectCost $lastDirectCost -Capacity $capacity.Value -Finish $finish -Material $material -Color $color

    $reviewReasons = [System.Collections.Generic.List[string]]::new()
    if (-not $item.VendorNo) { $reviewReasons.Add('Missing Vendor No.') }
    if ($lastDirectCost -le 0) { $reviewReasons.Add('Missing Last Direct Cost') }
    if ($category -in @('BOTTLE','JAR','CAN','TUBE') -and -not $capacity.Value) { $reviewReasons.Add('Capacity not parsed') }
    if ($category -in @('BOTTLE','JAR','CAN','CAP','CANEND','CROWN','BARTOP','PUMP') -and -not $finish) { $reviewReasons.Add('Finish not parsed') }
    if ($category -in @('BOTTLE','JAR','CAN','CAP','CANEND','CROWN','BARTOP','TUBE') -and -not $material) { $reviewReasons.Add('Material not parsed') }
    if ($category -in @('BOTTLE','JAR','CAP','CANEND','CROWN','BARTOP','PUMP') -and -not $color) { $reviewReasons.Add('Color not parsed') }
    if ($category -in @('CARRIER','CARTON','FLEX')) { $reviewReasons.Add('Category requires manual mapping policy before auto-seed') }

    $candidates.Add([pscustomobject]@{
        AutoSeedEligible = $autoEligible
        Confidence = $confidence.Label
        ConfidenceScore = $confidence.Score
        ReviewReasons = ($reviewReasons -join '; ')
        ItemCategoryCode = $category
        GamerID = [string]$item.ItemNo
        BCItemNo = [string]$item.ItemNo
        Description = [string]$item.Description
        Description2 = [string]$item.Description2
        VendorNo = [string]$item.VendorNo
        SupplierMoldNo = [string]$item.VendorItemNo
        CurrentSupplierUnitCost = $lastDirectCost
        PriceSource = 'BC Item Last Direct Cost'
        Material = $material
        Capacity = $capacity.Value
        CapacityUOM = $capacity.Uom
        Finish = $finish
        FinishType = $finishType
        Color = $color
        Style = $style
        Packout = $packout
        GramWeight = $gramWeight
        BaseUnitOfMeasure = [string]$item.BaseUnitOfMeasure
    }) | Out-Null
}

$previewPath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Seed_Preview.csv'
$reviewPath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_Seed_Review.csv'
$eligiblePath = Join-Path $DiscoveryFolder 'BC_Packaging_Catalog_AutoSeed_Eligible.csv'

$candidates |
    Sort-Object ItemCategoryCode, GamerID |
    Export-Csv -LiteralPath $previewPath -NoTypeInformation -Encoding UTF8

$candidates |
    Where-Object { -not $_.AutoSeedEligible } |
    Sort-Object ItemCategoryCode, ConfidenceScore -Descending |
    Export-Csv -LiteralPath $reviewPath -NoTypeInformation -Encoding UTF8

$candidates |
    Where-Object { $_.AutoSeedEligible } |
    Sort-Object ItemCategoryCode, GamerID |
    Export-Csv -LiteralPath $eligiblePath -NoTypeInformation -Encoding UTF8

$summary = @(
    $candidates |
        Group-Object ItemCategoryCode |
        ForEach-Object {
            [pscustomobject]@{
                Category = $_.Name
                Candidates = $_.Count
                AutoSeedEligible = @($_.Group | Where-Object { $_.AutoSeedEligible }).Count
                HighConfidence = @($_.Group | Where-Object { $_.Confidence -eq 'High' }).Count
                MediumConfidence = @($_.Group | Where-Object { $_.Confidence -eq 'Medium' }).Count
                LowConfidence = @($_.Group | Where-Object { $_.Confidence -eq 'Low' }).Count
                WithCapacity = @($_.Group | Where-Object { $_.Capacity }).Count
                WithFinish = @($_.Group | Where-Object { $_.Finish }).Count
                WithMaterial = @($_.Group | Where-Object { $_.Material }).Count
                WithColor = @($_.Group | Where-Object { $_.Color }).Count
                WithCost = @($_.Group | Where-Object { [decimal]$_.CurrentSupplierUnitCost -gt 0 }).Count
            }
        } |
        Sort-Object Candidates -Descending
)

Write-Host ''
Write-Host 'GPI BC ITEM TO PACKAGING CATALOG SEED PREVIEW' -ForegroundColor Cyan
Write-Host "Discovery folder : $DiscoveryFolder"
Write-Host "Candidates       : $($candidates.Count)"
Write-Host "Auto-seed eligible: $(@($candidates | Where-Object { $_.AutoSeedEligible }).Count)"
Write-Host ''
Write-Host 'CATEGORY SUMMARY' -ForegroundColor Cyan
$summary | Format-Table -AutoSize

Write-Host ''
Write-Host 'SAMPLE AUTO-SEED ELIGIBLE RECORDS' -ForegroundColor Cyan
$candidates |
    Where-Object { $_.AutoSeedEligible } |
    Sort-Object ConfidenceScore -Descending |
    Select-Object -First 20 ItemCategoryCode, GamerID, VendorNo, CurrentSupplierUnitCost, Material, Capacity, CapacityUOM, Finish, FinishType, Color, Style, GramWeight |
    Format-Table -AutoSize -Wrap

Write-Host ''
Write-Host 'SAMPLE REVIEW RECORDS' -ForegroundColor Cyan
$candidates |
    Where-Object { -not $_.AutoSeedEligible } |
    Sort-Object ConfidenceScore -Descending |
    Select-Object -First 20 ItemCategoryCode, GamerID, Confidence, ReviewReasons, Material, Capacity, CapacityUOM, Finish, Color, Style |
    Format-Table -AutoSize -Wrap

Write-Host ''
Write-Host 'Created:' -ForegroundColor Green
Write-Host "  $previewPath"
Write-Host "  $eligiblePath"
Write-Host "  $reviewPath"
Write-Host ''
Write-Host 'PREVIEW ONLY. No Business Central data was changed.'
