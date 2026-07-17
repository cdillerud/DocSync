[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.10"
$ExpectedTestVersion = "0.8.0.10"
$NewProductionVersion = "0.27.0.11"
$NewTestVersion = "0.8.0.11"

$ProductionRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement-tests"

$ProductionAppJson = Join-Path -Path $ProductionRoot -ChildPath "app.json"
$TestAppJson = Join-Path -Path $TestRoot -ChildPath "app.json"
$ChangeLog = Join-Path -Path $ProductionRoot -ChildPath "CHANGELOG.md"
$BuildScript = Join-Path -Path $RepoRoot -ChildPath "scripts\Prepare-GPIALTests.ps1"
$ReportLayoutFolder = Join-Path -Path $ProductionRoot -ChildPath "src\reportlayout"

$RequiredPaths = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog,
    $BuildScript,
    $ReportLayoutFolder
)

foreach ($RequiredPath in $RequiredPaths) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required path was not found: $RequiredPath"
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Content
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Encoding)
}

function Write-JsonNoBom {
    param(
        [Parameter(Mandatory)][object]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    $Json = $Value | ConvertTo-Json -Depth 100
    Write-Utf8NoBom -Path $Path -Content ($Json + [Environment]::NewLine)
}

function Get-LineEnding {
    param([Parameter(Mandatory)][string]$Content)

    if ($Content.Contains("`r`n")) {
        return "`r`n"
    }

    return "`n"
}

function Convert-InchTextToDecimal {
    param([string]$ValueText)

    if ([string]::IsNullOrWhiteSpace($ValueText)) {
        return 0.0
    }

    $Clean = $ValueText.Trim().Replace("in", "")
    $Value = 0.0
    [void][double]::TryParse(
        $Clean,
        [System.Globalization.NumberStyles]::Float,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [ref]$Value)

    return $Value
}

function Format-Inches {
    param([double]$Value)

    return ($Value.ToString("0.###", [System.Globalization.CultureInfo]::InvariantCulture) + "in")
}

function Get-TagInches {
    param(
        [Parameter(Mandatory)][string]$Xml,
        [Parameter(Mandatory)][string]$TagName
    )

    $Match = [regex]::Match($Xml, "(?s)<$TagName>([0-9.]+)in</$TagName>")
    if (-not $Match.Success) {
        return 0.0
    }

    return Convert-InchTextToDecimal $Match.Groups[1].Value
}

function Set-SimpleTagValue {
    param(
        [Parameter(Mandatory)][string]$Xml,
        [Parameter(Mandatory)][string]$TagName,
        [Parameter(Mandatory)][string]$Value
    )

    if ($Xml -match "(?s)<$TagName>.*?</$TagName>") {
        return [regex]::Replace($Xml, "(?s)<$TagName>.*?</$TagName>", "<$TagName>$Value</$TagName>", 1)
    }

    return [regex]::Replace(
        $Xml,
        "(?s)</Textbox>",
        "            <$TagName>$Value</$TagName>`r`n          </Textbox>",
        1)
}

function Ensure-ParagraphTextAlign {
    param(
        [Parameter(Mandatory)][string]$TextboxXml,
        [Parameter(Mandatory)][ValidateSet("Left","Center","Right")][string]$Alignment
    )

    if ($TextboxXml -match "(?s)<TextAlign>.*?</TextAlign>") {
        return [regex]::Replace($TextboxXml, "(?s)<TextAlign>.*?</TextAlign>", "<TextAlign>$Alignment</TextAlign>", 1)
    }

    $ParagraphStyleMatch = [regex]::Match($TextboxXml, "(?s)(<Paragraph>.*?<Style>)(.*?)(</Style>)")
    if ($ParagraphStyleMatch.Success) {
        return $TextboxXml.Substring(0, $ParagraphStyleMatch.Groups[3].Index) +
            "                  <TextAlign>$Alignment</TextAlign>`r`n" +
            $TextboxXml.Substring($ParagraphStyleMatch.Groups[3].Index)
    }

    return [regex]::Replace(
        $TextboxXml,
        "(?s)(</Paragraph>)",
        "                <Style>`r`n                  <TextAlign>$Alignment</TextAlign>`r`n                </Style>`r`n              `$1",
        1)
}

function Ensure-TextRunStyleValue {
    param(
        [Parameter(Mandatory)][string]$TextboxXml,
        [Parameter(Mandatory)][string]$TagName,
        [Parameter(Mandatory)][string]$Value
    )

    $TextRunMatches = @([regex]::Matches($TextboxXml, '(?s)<TextRun>.*?</TextRun>'))
    if ($TextRunMatches.Count -eq 0) {
        return $TextboxXml
    }

    $Updated = $TextboxXml
    for ($Index = $TextRunMatches.Count - 1; $Index -ge 0; $Index--) {
        $Match = $TextRunMatches[$Index]
        $RunXml = $Match.Value

        if ($RunXml -match "(?s)<$TagName>.*?</$TagName>") {
            $NewRunXml = [regex]::Replace($RunXml, "(?s)<$TagName>.*?</$TagName>", "<$TagName>$Value</$TagName>", 1)
        }
        elseif ($RunXml -match "(?s)<Style>.*?</Style>") {
            $NewRunXml = [regex]::Replace($RunXml, "(?s)</Style>", "                      <$TagName>$Value</$TagName>`r`n                    </Style>", 1)
        }
        else {
            $NewRunXml = [regex]::Replace(
                $RunXml,
                "(?s)</TextRun>",
                "                    <Style>`r`n                      <$TagName>$Value</$TagName>`r`n                    </Style>`r`n                  </TextRun>",
                1)
        }

        $Updated = $Updated.Substring(0, $Match.Index) + $NewRunXml + $Updated.Substring($Match.Index + $Match.Length)
    }

    return $Updated
}

function Ensure-TextboxFontWeight {
    param(
        [Parameter(Mandatory)][string]$TextboxXml,
        [Parameter(Mandatory)][string]$Weight
    )

    return Ensure-TextRunStyleValue -TextboxXml $TextboxXml -TagName "FontWeight" -Value $Weight
}

function Ensure-TextRunFormat {
    param(
        [Parameter(Mandatory)][string]$TextboxXml,
        [Parameter(Mandatory)][string]$Format
    )

    return Ensure-TextRunStyleValue -TextboxXml $TextboxXml -TagName "Format" -Value $Format
}

function Get-TextboxName {
    param([Parameter(Mandatory)][string]$Xml)

    $Match = [regex]::Match($Xml, '<Textbox\s+Name="([^"]+)"')
    if ($Match.Success) {
        return $Match.Groups[1].Value
    }

    return ""
}

function Test-IsFieldTextbox {
    param([Parameter(Mandatory)][string]$Xml)

    return ($Xml -match 'Fields![A-Za-z0-9_]+\.Value')
}

function Get-Classification {
    param([Parameter(Mandatory)][string]$Xml)

    $Name = (Get-TextboxName -Xml $Xml).ToLowerInvariant()
    $Lower = $Xml.ToLowerInvariant()
    $HasFields = Test-IsFieldTextbox -Xml $Xml

    $Result = [ordered]@{
        Alignment = ""
        Format = ""
        Header = $false
        Kind = ""
    }

    $IsUom =
        ($Name -match '(^|[^a-z])(uom|u_o_m|unitofmeasure|unit_of_measure|unitmeasure)([^a-z]|$)') -or
        ($Lower -match 'fields![a-z0-9_]*(uom|unitofmeasure|unit_of_measure|unit measure|unitofmeasurecode|unitofmeasurecode)[a-z0-9_]*\.value') -or
        ($Lower -match 'unit of measure') -or
        ($Lower -match '>uom<') -or
        ($Lower -match '>uom code<')

    $IsQuantity =
        ($Lower -match 'fields![a-z0-9_]*(quantity|qty|qtytoship|qtytoinvoice|outstandingqty|qtyreceived|qtyshipped|basequantity)[a-z0-9_]*\.value') -or
        ($Name -match '(quantity|qty)')

    $IsPrice =
        ($Lower -match 'fields![a-z0-9_]*(unitprice|unit_price|price|directunitcost|unitcost|unit_cost)[a-z0-9_]*\.value') -or
        ($Name -match '(unitprice|price|unitcost|directunitcost)')

    $IsAmount =
        ($Lower -match 'fields![a-z0-9_]*(lineamount|line_amount|amount|extendedprice|extprice|total|subtotal|tax|cost)[a-z0-9_]*\.value') -or
        ($Name -match '(lineamount|amount|extendedprice|total|subtotal|tax)')

    $IsDescription =
        ($Lower -match 'fields![a-z0-9_]*(description|extendedtext)[a-z0-9_]*\.value') -or
        ($Name -match '(description|extendedtext)')

    $IsItem =
        ($Lower -match 'fields![a-z0-9_]*(itemno|item_no|vendoritem|vendor_item|no_?|number)[a-z0-9_]*\.value') -or
        ($Name -match '(item|vendoritem|itemno)')

    if ($IsUom) {
        $Result.Alignment = "Center"
        $Result.Kind = "UoM"
        return $Result
    }

    if ($IsQuantity) {
        $Result.Alignment = "Right"
        $Result.Format = "#,##0.##"
        $Result.Kind = "Quantity"
        return $Result
    }

    if ($IsPrice) {
        $Result.Alignment = "Right"
        $Result.Format = "#,##0.00"
        $Result.Kind = "Price"
        return $Result
    }

    if ($IsAmount) {
        $Result.Alignment = "Right"
        $Result.Format = "#,##0.00"
        $Result.Kind = "Amount"
        return $Result
    }

    if ($IsDescription -or $IsItem) {
        $Result.Alignment = "Left"
        $Result.Kind = "Text"
        return $Result
    }

    if (-not $HasFields) {
        if (($Lower -match '>qty<') -or ($Lower -match '>quantity<') -or ($Lower -match '>amount<') -or ($Lower -match '>price<') -or ($Lower -match '>uom<') -or ($Lower -match 'unit of measure')) {
            $Result.Alignment = "Center"
            $Result.Header = $true
            $Result.Kind = "Header"
            return $Result
        }
    }

    return $Result
}

function Set-LineGridTextboxFormatting {
    param([Parameter(Mandatory)][string]$Content)

    $Matches = @([regex]::Matches($Content, '(?s)<Textbox\b[^>]*>.*?</Textbox>'))
    $Updated = $Content
    $ChangeCount = 0

    for ($Index = $Matches.Count - 1; $Index -ge 0; $Index--) {
        $Match = $Matches[$Index]
        $Old = $Match.Value
        $Class = Get-Classification -Xml $Old

        if ([string]::IsNullOrWhiteSpace($Class.Alignment)) {
            continue
        }

        $New = Ensure-ParagraphTextAlign -TextboxXml $Old -Alignment $Class.Alignment

        if ($Class.Header) {
            $New = Ensure-TextboxFontWeight -TextboxXml $New -Weight "Bold"
        }

        if (-not [string]::IsNullOrWhiteSpace($Class.Format)) {
            $New = Ensure-TextRunFormat -TextboxXml $New -Format $Class.Format
        }

        if ($Class.Kind -eq "UoM") {
            if ($New -match '<Width>[0-9.]+in</Width>') {
                $CurrentWidth = Get-TagInches -Xml $New -TagName "Width"
                if (($CurrentWidth -gt 0.55) -and ($CurrentWidth -lt 1.3)) {
                    $New = Set-SimpleTagValue -Xml $New -TagName "Width" -Value "0.55in"
                }
            }
        }

        if ($New -ne $Old) {
            $Updated = $Updated.Substring(0, $Match.Index) + $New + $Updated.Substring($Match.Index + $Match.Length)
            $ChangeCount++
        }
    }

    return [pscustomobject]@{
        Content = $Updated
        ChangeCount = $ChangeCount
    }
}

function Get-FieldTextboxMatch {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$FieldName
    )

    $Pattern = "(?s)<Textbox\b[^>]*>.*?Fields!$FieldName\.Value.*?</Textbox>"
    $Matches = @([regex]::Matches($Content, $Pattern))
    if ($Matches.Count -eq 0) {
        return $null
    }

    $Best = $null
    $BestScore = -9999

    foreach ($Match in $Matches) {
        $Xml = $Match.Value
        $Top = Get-TagInches -Xml $Xml -TagName "Top"
        $Left = Get-TagInches -Xml $Xml -TagName "Left"
        $Score = 0

        if ($Top -le 2.5) { $Score += 50 }
        if ($Top -le 1.5) { $Score += 50 }
        if ($Left -gt 3.5) { $Score += 25 }
        if ((Get-TextboxName -Xml $Xml).ToLowerInvariant() -match 'gamer|contact') { $Score += 50 }

        if ($Score -gt $BestScore) {
            $BestScore = $Score
            $Best = $Match
        }
    }

    return $Best
}

function Set-GamerContactStacking {
    param([Parameter(Mandatory)][string]$Content)

    $Match1 = Get-FieldTextboxMatch -Content $Content -FieldName "GamerContactName1"
    $Match2 = Get-FieldTextboxMatch -Content $Content -FieldName "GamerContactName2"

    if (($null -eq $Match1) -or ($null -eq $Match2)) {
        return [pscustomobject]@{
            Content = $Content
            Changed = $false
        }
    }

    $Box1 = $Match1.Value
    $Box2 = $Match2.Value

    $Left = Get-TagInches -Xml $Box1 -TagName "Left"
    $Top = Get-TagInches -Xml $Box1 -TagName "Top"
    $Height = Get-TagInches -Xml $Box1 -TagName "Height"
    $Width = Get-TagInches -Xml $Box1 -TagName "Width"

    if ($Height -le 0) { $Height = 0.18 }
    if ($Width -le 0) { $Width = 2.25 }

    $NewBox1 = $Box1
    $NewBox2 = $Box2

    $NewBox1 = Set-SimpleTagValue -Xml $NewBox1 -TagName "Left" -Value (Format-Inches $Left)
    $NewBox1 = Set-SimpleTagValue -Xml $NewBox1 -TagName "Width" -Value (Format-Inches $Width)
    $NewBox1 = Ensure-ParagraphTextAlign -TextboxXml $NewBox1 -Alignment "Left"

    $NewBox2 = Set-SimpleTagValue -Xml $NewBox2 -TagName "Left" -Value (Format-Inches $Left)
    $NewBox2 = Set-SimpleTagValue -Xml $NewBox2 -TagName "Top" -Value (Format-Inches ($Top + $Height + 0.02))
    $NewBox2 = Set-SimpleTagValue -Xml $NewBox2 -TagName "Width" -Value (Format-Inches $Width)
    $NewBox2 = Ensure-ParagraphTextAlign -TextboxXml $NewBox2 -Alignment "Left"

    $FirstIndex = [Math]::Max($Match1.Index, $Match2.Index)
    $SecondIndex = [Math]::Min($Match1.Index, $Match2.Index)

    $Updated = $Content

    if ($Match1.Index -gt $Match2.Index) {
        $Updated = $Updated.Substring(0, $Match1.Index) + $NewBox1 + $Updated.Substring($Match1.Index + $Match1.Length)
        $Updated = $Updated.Substring(0, $Match2.Index) + $NewBox2 + $Updated.Substring($Match2.Index + $Match2.Length)
    }
    else {
        $Updated = $Updated.Substring(0, $Match2.Index) + $NewBox2 + $Updated.Substring($Match2.Index + $Match2.Length)
        $Updated = $Updated.Substring(0, $Match1.Index) + $NewBox1 + $Updated.Substring($Match1.Index + $Match1.Length)
    }

    return [pscustomobject]@{
        Content = $Updated
        Changed = ($Updated -ne $Content)
    }
}

function Update-LayoutFormatting {
    param([Parameter(Mandatory)][string]$LayoutPath)

    $LayoutName = [System.IO.Path]::GetFileName($LayoutPath)
    $Original = Get-Content -LiteralPath $LayoutPath -Raw

    $LineGridResult = Set-LineGridTextboxFormatting -Content $Original
    $ContactResult = Set-GamerContactStacking -Content $LineGridResult.Content

    try {
        [xml]$XmlCheck = $ContactResult.Content
    }
    catch {
        throw "The updated RDL XML for $LayoutName is not valid XML: $($_.Exception.Message)"
    }

    if ($ContactResult.Content -ne $Original) {
        Write-Utf8NoBom -Path $LayoutPath -Content $ContactResult.Content
    }

    return [pscustomobject]@{
        Layout = $LayoutName
        TextboxesFormatted = $LineGridResult.ChangeCount
        GamerContactsStacked = [bool]$ContactResult.Changed
        Changed = ($ContactResult.Content -ne $Original)
    }
}

$ProductionApp = Get-Content -LiteralPath $ProductionAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

if ([string]$ProductionApp.version -ne $ExpectedProductionVersion) {
    throw "Expected production version $ExpectedProductionVersion, but found $($ProductionApp.version). Run the 0.27.0.10 header document-number patch first, then rerun this. No files were changed."
}

if ([string]$TestApp.version -ne $ExpectedTestVersion) {
    throw "Expected test version $ExpectedTestVersion, but found $($TestApp.version). Run the 0.27.0.10 header document-number patch first, then rerun this. No files were changed."
}

$MainDependency = @(
    $TestApp.dependencies |
        Where-Object { [string]$_.id -eq [string]$ProductionApp.id }
)

if ($MainDependency.Count -ne 1) {
    throw "Expected exactly one test dependency on production app $($ProductionApp.id), but found $($MainDependency.Count). No files were changed."
}

$LayoutFiles = @(
    "GPISalesOrderConfirmationBranded.rdl",
    "GPIPrepaymentNotice.rdl",
    "GPIPickTicket.rdl",
    "GPIBlanketSalesOrderBranded.rdl",
    "GPIDropShipPurchaseOrderBranded.rdl",
    "GPIWarehousePurchaseOrderBranded.rdl",
    "GPIWarehouseReceivingNoticeBranded.rdl",
    "GPISalesInvoiceBranded.rdl",
    "GPISalesCreditMemoBranded.rdl",
    "GPIPurchaseCreditMemoBranded.rdl",
    "GPISalesReturnAuthorizationBranded.rdl",
    "GPISalesReturnWarehouseNotificationBranded.rdl",
    "GPIPurchaseReturnOrderBranded.rdl",
    "GPIPurchaseReturnPickTicketBranded.rdl",
    "GPITransferPickListBranded.rdl",
    "GPITransferReceiptNotificationBranded.rdl",
    "GPICustomerOpenOrderStatusBranded.rdl"
) | ForEach-Object { Join-Path -Path $ReportLayoutFolder -ChildPath $_ }

foreach ($LayoutFile in $LayoutFiles) {
    if (-not (Test-Path -LiteralPath $LayoutFile)) {
        throw "Layout file was not found: $LayoutFile"
    }
}

$FilesToBackup = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog
) + $LayoutFiles

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\line-grid-formatting-0270011-$Timestamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

foreach ($Path in $FilesToBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path -Path $BackupRoot -ChildPath $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$ProductionApp.version = $NewProductionVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProductionVersion

$ChangeLogOriginal = Get-Content -LiteralPath $ChangeLog -Raw
$ChangeLogEntry = @"
## $NewProductionVersion

### Changed
- Standardized line-grid alignment across supported document layouts.
- UoM fields are centered and kept narrow where safe.
- Quantity fields are right-aligned and formatted as #,##0.##.
- Price and amount fields are right-aligned and formatted as #,##0.00.
- Text fields such as item, vendor item, description, and extended text are left-aligned.
- Header labels for quantity, UoM, price, and amount are centered and bolded.
- Gamer contact names are vertically stacked and aligned where the layout has GamerContactName1 and GamerContactName2 textboxes.

### Safety
- No dataset fields, line filtering, extended-text logic, footer text, recipient logic, sender logic, routing rules, Delivery Log, SharePoint archive, or email behavior was changed.
- No package is published automatically.
- Publish only to Sandbox_NoZetadocs_UAT or Sandbox_5_5_2026 unless Chad explicitly approves another environment.

"@

if ($ChangeLogOriginal -match '(?m)^# Changelog\s*$') {
    $UpdatedChangeLog = [regex]::Replace(
        $ChangeLogOriginal,
        '(?m)^# Changelog\s*$',
        "# Changelog`r`n`r`n$ChangeLogEntry",
        1
    )
}
else {
    throw "The changelog header was not found. No files were changed."
}

$ProductionPackage = Join-Path -Path $ProductionRoot -ChildPath "Gamer Packaging_GPI Sales Document Email_$NewProductionVersion.app"
$TestPackage = Join-Path -Path $TestRoot -ChildPath "Gamer Packaging_GPI Sales Document Email Tests_$NewTestVersion.app"

try {
    $Results = @()
    foreach ($LayoutFile in $LayoutFiles) {
        $Results += Update-LayoutFormatting -LayoutPath $LayoutFile
    }

    $ChangedCount = @($Results | Where-Object { $_.Changed }).Count
    if ($ChangedCount -eq 0) {
        throw "No layout formatting changes were made. No files were changed."
    }

    Write-JsonNoBom -Value $ProductionApp -Path $ProductionAppJson
    Write-JsonNoBom -Value $TestApp -Path $TestAppJson
    Write-Utf8NoBom -Path $ChangeLog -Content $UpdatedChangeLog

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " GPI line-grid formatting pass 0.27.0.11" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Layouts scanned:    $($Results.Count)"
    Write-Host "Layouts changed:    $ChangedCount"
    Write-Host "Backup:             $BackupRoot"
    Write-Host ""

    foreach ($Result in $Results) {
        Write-Host ("{0}: formatted={1}; gamer contacts stacked={2}" -f $Result.Layout, $Result.TextboxesFormatted, $Result.GamerContactsStacked)
    }

    Write-Host ""
    Write-Host "Running production and test builds..." -ForegroundColor Cyan

    & $BuildScript

    if (-not (Test-Path -LiteralPath $ProductionPackage)) {
        throw "The expected production package was not created: $ProductionPackage"
    }

    if (-not (Test-Path -LiteralPath $TestPackage)) {
        throw "The expected test package was not created: $TestPackage"
    }
}
catch {
    Write-Host ""
    Write-Host "The line-grid formatting build failed. Restoring modified files." -ForegroundColor Red

    foreach ($Path in $FilesToBackup) {
        $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path -Path $BackupRoot -ChildPath $RelativePath
        Copy-Item -LiteralPath $BackupPath -Destination $Path -Force
    }

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    throw
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " GPI 0.27.0.11 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production first, then tests only after production 0.27.0.11 is installed in the sandbox." -ForegroundColor Yellow
