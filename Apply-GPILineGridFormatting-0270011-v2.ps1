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

function Get-RdlNamespaceManager {
    param([Parameter(Mandatory)][System.Xml.XmlDocument]$Doc)

    $NsMgr = New-Object System.Xml.XmlNamespaceManager($Doc.NameTable)
    $NsMgr.AddNamespace("rdl", $Doc.DocumentElement.NamespaceURI)
    return $NsMgr
}

function Ensure-ChildElement {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Parent,
        [Parameter(Mandatory)][string]$LocalName,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Child = $Parent.SelectSingleNode("rdl:$LocalName", $NsMgr)
    if ($null -eq $Child) {
        $Child = $Doc.CreateElement($LocalName, $Doc.DocumentElement.NamespaceURI)
        [void]$Parent.AppendChild($Child)
    }

    return [System.Xml.XmlElement]$Child
}

function Set-ChildText {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Parent,
        [Parameter(Mandatory)][string]$LocalName,
        [Parameter(Mandatory)][string]$Value,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Child = Ensure-ChildElement -Doc $Doc -Parent $Parent -LocalName $LocalName -NsMgr $NsMgr
    $Child.InnerText = $Value
}

function Set-ParagraphAlignment {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][ValidateSet("Left","Center","Right")][string]$Alignment,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Paragraphs = @($Textbox.SelectNodes(".//rdl:Paragraph", $NsMgr))
    foreach ($Paragraph in $Paragraphs) {
        $Style = Ensure-ChildElement -Doc $Doc -Parent ([System.Xml.XmlElement]$Paragraph) -LocalName "Style" -NsMgr $NsMgr
        Set-ChildText -Doc $Doc -Parent $Style -LocalName "TextAlign" -Value $Alignment -NsMgr $NsMgr
    }
}

function Set-TextRunStyleText {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$TextRun,
        [Parameter(Mandatory)][string]$LocalName,
        [Parameter(Mandatory)][string]$Value,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Style = Ensure-ChildElement -Doc $Doc -Parent $TextRun -LocalName "Style" -NsMgr $NsMgr
    Set-ChildText -Doc $Doc -Parent $Style -LocalName $LocalName -Value $Value -NsMgr $NsMgr
}

function Set-TextboxTextRunFormat {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][string]$Format,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $TextRuns = @($Textbox.SelectNodes(".//rdl:TextRun", $NsMgr))
    foreach ($TextRun in $TextRuns) {
        Set-TextRunStyleText -Doc $Doc -TextRun ([System.Xml.XmlElement]$TextRun) -LocalName "Format" -Value $Format -NsMgr $NsMgr
    }
}

function Set-TextboxTextRunFontWeight {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][string]$FontWeight,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $TextRuns = @($Textbox.SelectNodes(".//rdl:TextRun", $NsMgr))
    foreach ($TextRun in $TextRuns) {
        Set-TextRunStyleText -Doc $Doc -TextRun ([System.Xml.XmlElement]$TextRun) -LocalName "FontWeight" -Value $FontWeight -NsMgr $NsMgr
    }
}

function Set-TextboxValueFormatExpression {
    param(
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][string]$FieldPattern,
        [Parameter(Mandatory)][string]$FormatText,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Values = @($Textbox.SelectNodes(".//rdl:Value", $NsMgr))
    foreach ($ValueNode in $Values) {
        $Text = [string]$ValueNode.InnerText
        if ($Text -match $FieldPattern) {
            $Text = [regex]::Replace(
                $Text,
                'Format\(([^,]+),\s*"[^"]*"\)',
                ('Format($1,"' + $FormatText + '")'))
            $ValueNode.InnerText = $Text
        }
    }
}

function Get-TextboxText {
    param([Parameter(Mandatory)][System.Xml.XmlElement]$Textbox)

    return ([string]$Textbox.InnerText)
}

function Get-TextboxName {
    param([Parameter(Mandatory)][System.Xml.XmlElement]$Textbox)

    return ([string]$Textbox.GetAttribute("Name"))
}

function Get-LineTextboxClassification {
    param([Parameter(Mandatory)][System.Xml.XmlElement]$Textbox)

    $Name = (Get-TextboxName -Textbox $Textbox).ToLowerInvariant()
    $Text = (Get-TextboxText -Textbox $Textbox).ToLowerInvariant()

    $Result = [ordered]@{
        Alignment = ""
        Format = ""
        IsHeader = $false
        Kind = ""
        NormalizeFormatExpression = $false
        FieldPattern = ""
    }

    $HasField = $Text -match 'fields![a-z0-9_]+\.value'

    $IsUom =
        ($Name -match 'uom|u_m|unitofmeasure|unit_of_measure|unitmeasure') -or
        ($Text -match 'fields![a-z0-9_]*(uom|unitofmeasure|unit_of_measure|unitofmeasurecode)[a-z0-9_]*\.value') -or
        ($Text -match 'unit of measure|^u/m$|^uom$|uom code')

    $IsQuantity =
        ($Name -match 'quantity|qty') -or
        ($Text -match 'fields![a-z0-9_]*(quantity|qty|qtytoship|qtytoinvoice|outstandingqty|qtyreceived|qtyshipped|basequantity)[a-z0-9_]*\.value') -or
        ((-not $HasField) -and ($Text -match '^qty\.?$|^quantity$'))

    $IsPrice =
        ($Name -match 'unitprice|price|unitcost|directunitcost') -or
        ($Text -match 'fields![a-z0-9_]*(unitprice|unit_price|price|directunitcost|unitcost|unit_cost)[a-z0-9_]*\.value') -or
        ((-not $HasField) -and ($Text -match 'price|cost'))

    $IsAmount =
        ($Name -match 'lineamount|amount|extendedprice|total|subtotal|tax') -or
        ($Text -match 'fields![a-z0-9_]*(lineamount|line_amount|amount|extendedprice|extprice|total|subtotal|tax|cost)[a-z0-9_]*\.value') -or
        ((-not $HasField) -and ($Text -match 'amount|total|subtotal|tax'))

    $IsDescription =
        ($Name -match 'description|extendedtext') -or
        ($Text -match 'fields![a-z0-9_]*(description|extendedtext)[a-z0-9_]*\.value') -or
        ((-not $HasField) -and ($Text -match '^description$'))

    $IsItem =
        ($Name -match 'item|vendoritem|itemno') -or
        ($Text -match 'fields![a-z0-9_]*(itemno|item_no|vendoritem|vendor_item|no)[a-z0-9_]*\.value') -or
        ((-not $HasField) -and ($Text -match '^item$|vendor item'))

    if (-not $HasField) {
        if ($IsUom -or $IsQuantity -or $IsPrice -or $IsAmount -or $IsDescription -or $IsItem) {
            $Result.IsHeader = $true
        }
    }

    if ($IsUom) {
        $Result.Alignment = "Center"
        $Result.Kind = "UoM"
        return $Result
    }

    if ($IsQuantity) {
        $Result.Alignment = "Right"
        $Result.Format = "#,##0.##"
        $Result.Kind = "Quantity"
        $Result.NormalizeFormatExpression = $true
        $Result.FieldPattern = 'Fields![A-Za-z0-9_]*(Quantity|Qty|QtyToShip|QtyToInvoice|OutstandingQty|QtyReceived|QtyShipped|BaseQuantity)[A-Za-z0-9_]*\.Value'
        return $Result
    }

    if ($IsPrice) {
        $Result.Alignment = "Right"
        $Result.Format = "#,##0.00"
        $Result.Kind = "Price"
        $Result.NormalizeFormatExpression = $true
        $Result.FieldPattern = 'Fields![A-Za-z0-9_]*(UnitPrice|Price|DirectUnitCost|UnitCost)[A-Za-z0-9_]*\.Value'
        return $Result
    }

    if ($IsAmount) {
        $Result.Alignment = "Right"
        $Result.Format = "#,##0.00"
        $Result.Kind = "Amount"
        $Result.NormalizeFormatExpression = $true
        $Result.FieldPattern = 'Fields![A-Za-z0-9_]*(LineAmount|Amount|ExtendedPrice|ExtPrice|Total|SubTotal|Tax|Cost)[A-Za-z0-9_]*\.Value'
        return $Result
    }

    if ($IsDescription -or $IsItem) {
        $Result.Alignment = "Left"
        $Result.Kind = "Text"
        return $Result
    }

    return $Result
}

function Update-TablixColumnWidths {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Tablix,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Changed = 0
    $Columns = @($Tablix.SelectNodes("rdl:TablixBody/rdl:TablixColumns/rdl:TablixColumn", $NsMgr))
    $FirstRowCells = @($Tablix.SelectNodes("rdl:TablixBody/rdl:TablixRows/rdl:TablixRow[1]/rdl:TablixCells/rdl:TablixCell", $NsMgr))

    for ($Index = 0; $Index -lt $FirstRowCells.Count; $Index++) {
        $CellText = ([string]$FirstRowCells[$Index].InnerText).ToLowerInvariant()
        if ($CellText -match 'u/m|uom|unit of measure') {
            if ($Index -lt $Columns.Count) {
                $WidthNode = $Columns[$Index].SelectSingleNode("rdl:Width", $NsMgr)
                if ($null -ne $WidthNode) {
                    $OldWidthText = [string]$WidthNode.InnerText
                    $OldWidth = 0.0
                    [void][double]::TryParse($OldWidthText.Replace("in", ""), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$OldWidth)
                    if (($OldWidth -gt 0.60) -and ($OldWidth -lt 1.25)) {
                        $WidthNode.InnerText = "0.55in"
                        $Changed++

                        $Delta = $OldWidth - 0.55
                        if (($Index -gt 0) -and ($Delta -gt 0)) {
                            $PreviousWidthNode = $Columns[$Index - 1].SelectSingleNode("rdl:Width", $NsMgr)
                            if ($null -ne $PreviousWidthNode) {
                                $PreviousWidth = 0.0
                                [void][double]::TryParse(([string]$PreviousWidthNode.InnerText).Replace("in", ""), [System.Globalization.NumberStyles]::Float, [System.Globalization.CultureInfo]::InvariantCulture, [ref]$PreviousWidth)
                                if ($PreviousWidth -gt 1.0) {
                                    $PreviousWidthNode.InnerText = (($PreviousWidth + $Delta).ToString("0.###", [System.Globalization.CultureInfo]::InvariantCulture) + "in")
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    return $Changed
}

function Update-LineGridFormatting {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Formatted = 0
    $ColumnChanges = 0
    $Tablixes = @($Doc.SelectNodes("//rdl:Tablix", $NsMgr))

    foreach ($Tablix in $Tablixes) {
        $ColumnChanges += Update-TablixColumnWidths -Doc $Doc -Tablix ([System.Xml.XmlElement]$Tablix) -NsMgr $NsMgr

        $Textboxes = @($Tablix.SelectNodes(".//rdl:Textbox", $NsMgr))
        foreach ($TextboxNode in $Textboxes) {
            $Textbox = [System.Xml.XmlElement]$TextboxNode
            $Class = Get-LineTextboxClassification -Textbox $Textbox

            if ([string]::IsNullOrWhiteSpace($Class.Alignment)) {
                continue
            }

            Set-ParagraphAlignment -Doc $Doc -Textbox $Textbox -Alignment $Class.Alignment -NsMgr $NsMgr

            if ($Class.IsHeader) {
                Set-TextboxTextRunFontWeight -Doc $Doc -Textbox $Textbox -FontWeight "Bold" -NsMgr $NsMgr
            }

            if (-not [string]::IsNullOrWhiteSpace($Class.Format)) {
                Set-TextboxTextRunFormat -Doc $Doc -Textbox $Textbox -Format $Class.Format -NsMgr $NsMgr
                if ($Class.NormalizeFormatExpression) {
                    Set-TextboxValueFormatExpression -Textbox $Textbox -FieldPattern $Class.FieldPattern -FormatText $Class.Format -NsMgr $NsMgr
                }
            }

            $Formatted++
        }
    }

    return [pscustomobject]@{
        FormattedTextboxes = $Formatted
        ColumnChanges = $ColumnChanges
    }
}

function Update-GamerContactAlignment {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Changed = 0
    $Textboxes = @($Doc.SelectNodes("//rdl:Textbox[not(ancestor::rdl:Tablix)]", $NsMgr))

    foreach ($TextboxNode in $Textboxes) {
        $Textbox = [System.Xml.XmlElement]$TextboxNode
        $Text = [string]$Textbox.InnerText

        if (($Text -notmatch 'GamerContactName1') -and ($Text -notmatch 'Gamer Contacts')) {
            continue
        }

        Set-ParagraphAlignment -Doc $Doc -Textbox $Textbox -Alignment "Left" -NsMgr $NsMgr

        $StaticLabelRuns = @($Textbox.SelectNodes(".//rdl:TextRun[rdl:Value='Gamer Contacts: ' or rdl:Value='Gamer Contacts:']", $NsMgr))
        foreach ($Run in $StaticLabelRuns) {
            $ValueNode = $Run.SelectSingleNode("rdl:Value", $NsMgr)
            if ($null -ne $ValueNode) {
                $ValueNode.InnerText = "Gamer Contacts:"
            }
        }

        $DynamicValues = @($Textbox.SelectNodes(".//rdl:TextRun/rdl:Value[contains(.,'GamerContactName1')]", $NsMgr))
        foreach ($ValueNode in $DynamicValues) {
            $Current = [string]$ValueNode.InnerText
            if ($Current -match '^=') {
                $ValueNode.InnerText = '=Trim(IIF(Len(Trim(First(Fields!GamerContactName1.Value,"DataSet_Result"))) > 0, vbCrLf & First(Fields!GamerContactName1.Value,"DataSet_Result"), "") & IIF(Len(Trim(First(Fields!GamerContactName2.Value,"DataSet_Result"))) > 0, vbCrLf & First(Fields!GamerContactName2.Value,"DataSet_Result"), ""))'
            }
        }

        $Changed++
    }

    return $Changed
}

function Save-XmlDocumentUtf8NoBom {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][string]$Path
    )

    $Settings = New-Object System.Xml.XmlWriterSettings
    $Settings.Encoding = New-Object System.Text.UTF8Encoding($false)
    $Settings.Indent = $true
    $Settings.OmitXmlDeclaration = $false

    $Writer = [System.Xml.XmlWriter]::Create($Path, $Settings)
    try {
        $Doc.Save($Writer)
    }
    finally {
        $Writer.Close()
    }
}

function Update-LayoutFormatting {
    param([Parameter(Mandatory)][string]$LayoutPath)

    $LayoutName = [System.IO.Path]::GetFileName($LayoutPath)
    $Original = Get-Content -LiteralPath $LayoutPath -Raw

    $Doc = New-Object System.Xml.XmlDocument
    $Doc.PreserveWhitespace = $false

    try {
        $Doc.Load($LayoutPath)
    }
    catch {
        throw "The original RDL XML for $LayoutName is not valid XML before changes: $($_.Exception.Message)"
    }

    $NsMgr = Get-RdlNamespaceManager -Doc $Doc

    $LineResult = Update-LineGridFormatting -Doc $Doc -NsMgr $NsMgr
    $GamerContactChanges = Update-GamerContactAlignment -Doc $Doc -NsMgr $NsMgr

    Save-XmlDocumentUtf8NoBom -Doc $Doc -Path $LayoutPath

    try {
        [xml]$XmlCheck = Get-Content -LiteralPath $LayoutPath -Raw
    }
    catch {
        throw "The updated RDL XML for $LayoutName is not valid XML after save: $($_.Exception.Message)"
    }

    $Updated = Get-Content -LiteralPath $LayoutPath -Raw

    return [pscustomobject]@{
        Layout = $LayoutName
        TextboxesFormatted = $LineResult.FormattedTextboxes
        UomColumnChanges = $LineResult.ColumnChanges
        GamerContactBlocksAligned = $GamerContactChanges
        Changed = ($Updated -ne $Original)
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
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\line-grid-formatting-0270011-v2-$Timestamp"
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
- UoM columns are centered and narrowed where safe, with reclaimed width assigned to the previous column.
- Quantity fields are right-aligned and formatted as #,##0.##.
- Price and amount fields are right-aligned and formatted as #,##0.00.
- Text fields such as item, vendor item, description, and extended text are left-aligned.
- Matching line-grid header labels are bolded.
- Gamer contact names are stacked under the Gamer Contacts label and left-aligned.

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
    Write-Host " GPI line-grid formatting pass 0.27.0.11 v2" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Layouts scanned:    $($Results.Count)"
    Write-Host "Layouts changed:    $ChangedCount"
    Write-Host "Backup:             $BackupRoot"
    Write-Host ""

    foreach ($Result in $Results) {
        Write-Host ("{0}: formatted={1}; UoM columns={2}; gamer contact blocks={3}" -f $Result.Layout, $Result.TextboxesFormatted, $Result.UomColumnChanges, $Result.GamerContactBlocksAligned)
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
