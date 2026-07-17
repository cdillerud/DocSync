[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.9"
$ExpectedTestVersion = "0.8.0.9"
$NewProductionVersion = "0.27.0.10"
$NewTestVersion = "0.8.0.10"

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

function Get-ElementText {
    param(
        [Parameter(Mandatory)][System.Xml.XmlElement]$Parent,
        [Parameter(Mandatory)][string]$LocalName,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Node = $Parent.SelectSingleNode("rdl:$LocalName", $NsMgr)
    if ($null -eq $Node) {
        return ""
    }

    return [string]$Node.InnerText
}

function Set-ChildElementText {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Parent,
        [Parameter(Mandatory)][string]$LocalName,
        [Parameter(Mandatory)][string]$Value,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Ns = $Doc.DocumentElement.NamespaceURI
    $Child = $Parent.SelectSingleNode("rdl:$LocalName", $NsMgr)

    if ($null -eq $Child) {
        $Child = $Doc.CreateElement($LocalName, $Ns)
        [void]$Parent.AppendChild($Child)
    }

    $Child.InnerText = $Value
}

function Ensure-ChildElement {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Parent,
        [Parameter(Mandatory)][string]$LocalName,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Ns = $Doc.DocumentElement.NamespaceURI
    $Child = $Parent.SelectSingleNode("rdl:$LocalName", $NsMgr)

    if ($null -eq $Child) {
        $Child = $Doc.CreateElement($LocalName, $Ns)
        [void]$Parent.AppendChild($Child)
    }

    return [System.Xml.XmlElement]$Child
}

function Set-TextboxStyleValue {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Value
    )

    $Style = Ensure-ChildElement -Doc $Doc -Parent $Textbox -LocalName "Style" -NsMgr $NsMgr
    Set-ChildElementText -Doc $Doc -Parent $Style -LocalName $Name -Value $Value -NsMgr $NsMgr
}

function Set-ParagraphTextAlignRight {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Paragraph = $Textbox.SelectSingleNode("rdl:Paragraphs/rdl:Paragraph", $NsMgr)
    if ($null -eq $Paragraph) {
        return
    }

    $ParagraphStyle = Ensure-ChildElement -Doc $Doc -Parent ([System.Xml.XmlElement]$Paragraph) -LocalName "Style" -NsMgr $NsMgr
    Set-ChildElementText -Doc $Doc -Parent $ParagraphStyle -LocalName "TextAlign" -Value "Right" -NsMgr $NsMgr
}

function Build-DocumentNumberTextbox {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr,
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string]$FieldName
    )

    $Ns = $Doc.DocumentElement.NamespaceURI

    $Textbox = $Doc.CreateElement("Textbox", $Ns)
    $Textbox.SetAttribute("Name", "GPIHeaderDocumentNumber")

    $CanGrow = $Doc.CreateElement("CanGrow", $Ns)
    $CanGrow.InnerText = "false"
    [void]$Textbox.AppendChild($CanGrow)

    $KeepTogether = $Doc.CreateElement("KeepTogether", $Ns)
    $KeepTogether.InnerText = "true"
    [void]$Textbox.AppendChild($KeepTogether)

    $Paragraphs = $Doc.CreateElement("Paragraphs", $Ns)
    $Paragraph = $Doc.CreateElement("Paragraph", $Ns)
    $TextRuns = $Doc.CreateElement("TextRuns", $Ns)
    $TextRun = $Doc.CreateElement("TextRun", $Ns)

    $Value = $Doc.CreateElement("Value", $Ns)
    $Value.InnerText = '="' + $Label + ': " & First(Fields!' + $FieldName + '.Value,"DataSet_Result")'
    [void]$TextRun.AppendChild($Value)

    $TextRunStyle = $Doc.CreateElement("Style", $Ns)
    foreach ($Pair in @(
        @{ Name = "FontFamily"; Value = "Arial" },
        @{ Name = "FontSize"; Value = "10pt" },
        @{ Name = "FontWeight"; Value = "Bold" },
        @{ Name = "Color"; Value = "#555555" }
    )) {
        $Node = $Doc.CreateElement($Pair.Name, $Ns)
        $Node.InnerText = $Pair.Value
        [void]$TextRunStyle.AppendChild($Node)
    }
    [void]$TextRun.AppendChild($TextRunStyle)

    [void]$TextRuns.AppendChild($TextRun)
    [void]$Paragraph.AppendChild($TextRuns)

    $ParagraphStyle = $Doc.CreateElement("Style", $Ns)
    $TextAlign = $Doc.CreateElement("TextAlign", $Ns)
    $TextAlign.InnerText = "Right"
    [void]$ParagraphStyle.AppendChild($TextAlign)
    [void]$Paragraph.AppendChild($ParagraphStyle)

    [void]$Paragraphs.AppendChild($Paragraph)
    [void]$Textbox.AppendChild($Paragraphs)

    $Style = $Doc.CreateElement("Style", $Ns)
    $Border = $Doc.CreateElement("Border", $Ns)
    $BorderStyle = $Doc.CreateElement("Style", $Ns)
    $BorderStyle.InnerText = "None"
    [void]$Border.AppendChild($BorderStyle)
    [void]$Style.AppendChild($Border)
    [void]$Textbox.AppendChild($Style)

    return [System.Xml.XmlElement]$Textbox
}

function Set-DocumentNumberTextbox {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr,
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string]$FieldName,
        [Parameter(Mandatory)][double]$Top,
        [Parameter(Mandatory)][double]$Left,
        [Parameter(Mandatory)][double]$Width
    )

    $ValueNode = $Textbox.SelectSingleNode("rdl:Paragraphs/rdl:Paragraph/rdl:TextRuns/rdl:TextRun/rdl:Value", $NsMgr)
    if ($null -eq $ValueNode) {
        throw "Selected document-number textbox does not have a normal Value node."
    }

    $ValueNode.InnerText = '="' + $Label + ': " & First(Fields!' + $FieldName + '.Value,"DataSet_Result")'

    Set-ChildElementText -Doc $Doc -Parent $Textbox -LocalName "Top" -Value (Format-Inches $Top) -NsMgr $NsMgr
    Set-ChildElementText -Doc $Doc -Parent $Textbox -LocalName "Left" -Value (Format-Inches $Left) -NsMgr $NsMgr
    Set-ChildElementText -Doc $Doc -Parent $Textbox -LocalName "Height" -Value "0.22in" -NsMgr $NsMgr
    Set-ChildElementText -Doc $Doc -Parent $Textbox -LocalName "Width" -Value (Format-Inches $Width) -NsMgr $NsMgr

    Set-TextboxStyleValue -Doc $Doc -Textbox $Textbox -NsMgr $NsMgr -Name "FontFamily" -Value "Arial"
    Set-TextboxStyleValue -Doc $Doc -Textbox $Textbox -NsMgr $NsMgr -Name "FontSize" -Value "10pt"
    Set-TextboxStyleValue -Doc $Doc -Textbox $Textbox -NsMgr $NsMgr -Name "FontWeight" -Value "Bold"
    Set-TextboxStyleValue -Doc $Doc -Textbox $Textbox -NsMgr $NsMgr -Name "Color" -Value "#555555"
    Set-ParagraphTextAlignRight -Doc $Doc -Textbox $Textbox -NsMgr $NsMgr

    $TextRunStyle = Ensure-ChildElement -Doc $Doc -Parent ([System.Xml.XmlElement]$Textbox.SelectSingleNode("rdl:Paragraphs/rdl:Paragraph/rdl:TextRuns/rdl:TextRun", $NsMgr)) -LocalName "Style" -NsMgr $NsMgr
    Set-ChildElementText -Doc $Doc -Parent $TextRunStyle -LocalName "FontFamily" -Value "Arial" -NsMgr $NsMgr
    Set-ChildElementText -Doc $Doc -Parent $TextRunStyle -LocalName "FontSize" -Value "10pt" -NsMgr $NsMgr
    Set-ChildElementText -Doc $Doc -Parent $TextRunStyle -LocalName "FontWeight" -Value "Bold" -NsMgr $NsMgr
    Set-ChildElementText -Doc $Doc -Parent $TextRunStyle -LocalName "Color" -Value "#555555" -NsMgr $NsMgr
}

function Find-DocumentNumberTextbox {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr,
        [Parameter(Mandatory)][string]$FieldName
    )

    $Textboxes = @($Doc.SelectNodes("//rdl:Textbox", $NsMgr))
    $NameHints = @(
        "documentno",
        "documentnumber",
        "orderno",
        "blanketorderno",
        "purchaseorderno",
        "invoiceno",
        "returnorderno",
        "transferorderno",
        "gpiheaderdocumentnumber"
    )

    $Best = $null

    foreach ($Textbox in $Textboxes) {
        $Name = $Textbox.GetAttribute("Name").ToLowerInvariant()
        $AllText = $Textbox.InnerText
        if ($AllText -notlike "*Fields!$FieldName.Value*") {
            continue
        }

        $HasTop = ($null -ne $Textbox.SelectSingleNode("rdl:Top", $NsMgr))
        $ValueCount = @($Textbox.SelectNodes(".//rdl:Value", $NsMgr)).Count
        $HasNameHint = $false
        foreach ($Hint in $NameHints) {
            if ($Name.Contains($Hint)) {
                $HasNameHint = $true
                break
            }
        }

        if (($HasTop -and $HasNameHint) -or ($HasTop -and $ValueCount -le 2)) {
            $Best = [System.Xml.XmlElement]$Textbox
            break
        }
    }

    return $Best
}

function Get-BodyWidth {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $WidthNode = $Doc.SelectSingleNode("//rdl:ReportSection/rdl:Body/rdl:Width", $NsMgr)
    if ($null -ne $WidthNode) {
        return (Convert-InchTextToDecimal $WidthNode.InnerText)
    }

    return 7.8
}

function Get-TitlePlacement {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $BodyWidth = Get-BodyWidth -Doc $Doc -NsMgr $NsMgr
    $DefaultWidth = 2.75
    $Placement = @{
        Top = 0.76
        Left = [Math]::Max(0, $BodyWidth - $DefaultWidth)
        Width = $DefaultWidth
    }

    $Title = $Doc.SelectSingleNode("//rdl:Textbox[@Name='Title']", $NsMgr)
    if ($null -eq $Title) {
        $Candidates = @($Doc.SelectNodes("//rdl:Textbox[rdl:Top and rdl:Left and rdl:Width]", $NsMgr))
        foreach ($Candidate in $Candidates) {
            $Top = Convert-InchTextToDecimal (Get-ElementText -Parent $Candidate -LocalName "Top" -NsMgr $NsMgr)
            $Left = Convert-InchTextToDecimal (Get-ElementText -Parent $Candidate -LocalName "Left" -NsMgr $NsMgr)
            $Text = $Candidate.InnerText.ToLowerInvariant()

            if (($Top -le 0.6) -and ($Left -ge ($BodyWidth / 2)) -and
                (($Text.Contains("order")) -or ($Text.Contains("invoice")) -or ($Text.Contains("memo")) -or ($Text.Contains("notice")) -or ($Text.Contains("ticket")) -or ($Text.Contains("receipt")) -or ($Text.Contains("transfer")))) {
                $Title = $Candidate
                break
            }
        }
    }

    if ($null -ne $Title) {
        $TitleTop = Convert-InchTextToDecimal (Get-ElementText -Parent $Title -LocalName "Top" -NsMgr $NsMgr)
        $TitleLeft = Convert-InchTextToDecimal (Get-ElementText -Parent $Title -LocalName "Left" -NsMgr $NsMgr)
        $TitleHeight = Convert-InchTextToDecimal (Get-ElementText -Parent $Title -LocalName "Height" -NsMgr $NsMgr)
        $TitleWidth = Convert-InchTextToDecimal (Get-ElementText -Parent $Title -LocalName "Width" -NsMgr $NsMgr)

        if ($TitleWidth -le 0) {
            $TitleWidth = $DefaultWidth
        }

        $Placement.Top = $TitleTop + $TitleHeight + 0.03
        $Placement.Left = $TitleLeft
        $Placement.Width = $TitleWidth
    }

    return $Placement
}

function Update-LayoutDocumentNumber {
    param(
        [Parameter(Mandatory)][string]$LayoutPath,
        [Parameter(Mandatory)][string]$FieldName,
        [Parameter(Mandatory)][string]$Label
    )

    $Doc = New-Object System.Xml.XmlDocument
    $Doc.PreserveWhitespace = $true
    $Doc.Load($LayoutPath)

    $NsMgr = New-Object System.Xml.XmlNamespaceManager($Doc.NameTable)
    $NsMgr.AddNamespace("rdl", $Doc.DocumentElement.NamespaceURI)

    $ReportItems = $Doc.SelectSingleNode("//rdl:ReportSection/rdl:Body/rdl:ReportItems", $NsMgr)
    if ($null -eq $ReportItems) {
        throw "Could not find Body/ReportItems in $LayoutPath."
    }

    $Placement = Get-TitlePlacement -Doc $Doc -NsMgr $NsMgr

    $Textbox = Find-DocumentNumberTextbox -Doc $Doc -NsMgr $NsMgr -FieldName $FieldName
    if ($null -eq $Textbox) {
        $Textbox = Build-DocumentNumberTextbox -Doc $Doc -NsMgr $NsMgr -Label $Label -FieldName $FieldName
        [void]$ReportItems.AppendChild($Textbox)
    }

    Set-DocumentNumberTextbox `
        -Doc $Doc `
        -Textbox $Textbox `
        -NsMgr $NsMgr `
        -Label $Label `
        -FieldName $FieldName `
        -Top ([double]$Placement.Top) `
        -Left ([double]$Placement.Left) `
        -Width ([double]$Placement.Width)

    $StringWriter = New-Object System.IO.StringWriter
    $XmlWriterSettings = New-Object System.Xml.XmlWriterSettings
    $XmlWriterSettings.Indent = $false
    $XmlWriterSettings.OmitXmlDeclaration = $false

    $XmlWriter = [System.Xml.XmlWriter]::Create($StringWriter, $XmlWriterSettings)
    $Doc.Save($XmlWriter)
    $XmlWriter.Close()

    $Output = $StringWriter.ToString()
    Write-Utf8NoBom -Path $LayoutPath -Content $Output
}

$ProductionApp = Get-Content -LiteralPath $ProductionAppJson -Raw | ConvertFrom-Json
$TestApp = Get-Content -LiteralPath $TestAppJson -Raw | ConvertFrom-Json

if ([string]$ProductionApp.version -ne $ExpectedProductionVersion) {
    throw "Expected production version $ExpectedProductionVersion, but found $($ProductionApp.version). No files were changed."
}

if ([string]$TestApp.version -ne $ExpectedTestVersion) {
    throw "Expected test version $ExpectedTestVersion, but found $($TestApp.version). No files were changed."
}

$MainDependency = @(
    $TestApp.dependencies |
        Where-Object { [string]$_.id -eq [string]$ProductionApp.id }
)

if ($MainDependency.Count -ne 1) {
    throw "Expected exactly one test dependency on production app $($ProductionApp.id), but found $($MainDependency.Count). No files were changed."
}

$LayoutMap = @(
    @{ File = "GPISalesOrderConfirmationBranded.rdl"; Field = "OrderNo"; Label = "Order #" },
    @{ File = "GPIPrepaymentNotice.rdl"; Field = "OrderNo"; Label = "Order #" },
    @{ File = "GPIPickTicket.rdl"; Field = "OrderNo"; Label = "Order #" },
    @{ File = "GPIBlanketSalesOrderBranded.rdl"; Field = "BlanketOrderNo"; Label = "Order #" },

    @{ File = "GPIDropShipPurchaseOrderBranded.rdl"; Field = "PurchaseOrderNo"; Label = "PO #" },
    @{ File = "GPIWarehousePurchaseOrderBranded.rdl"; Field = "PurchaseOrderNo"; Label = "PO #" },
    @{ File = "GPIWarehouseReceivingNoticeBranded.rdl"; Field = "PurchaseOrderNo"; Label = "PO #" },

    @{ File = "GPISalesInvoiceBranded.rdl"; Field = "InvoiceNo"; Label = "Invoice #" },
    @{ File = "GPISalesCreditMemoBranded.rdl"; Field = "InvoiceNo"; Label = "Credit Memo #" },
    @{ File = "GPIPurchaseCreditMemoBranded.rdl"; Field = "InvoiceNo"; Label = "Credit Memo #" },

    @{ File = "GPISalesReturnAuthorizationBranded.rdl"; Field = "ReturnOrderNo"; Label = "Return Order #" },
    @{ File = "GPISalesReturnWarehouseNotificationBranded.rdl"; Field = "ReturnOrderNo"; Label = "Return Order #" },
    @{ File = "GPIPurchaseReturnOrderBranded.rdl"; Field = "ReturnOrderNo"; Label = "Return Order #" },
    @{ File = "GPIPurchaseReturnPickTicketBranded.rdl"; Field = "ReturnOrderNo"; Label = "Return Order #" },

    @{ File = "GPITransferPickListBranded.rdl"; Field = "TransferOrderNo"; Label = "Transfer Order #" },
    @{ File = "GPITransferReceiptNotificationBranded.rdl"; Field = "TransferOrderNo"; Label = "Transfer Order #" }
)

$LayoutPaths = @()
foreach ($Map in $LayoutMap) {
    $LayoutPath = Join-Path -Path $ReportLayoutFolder -ChildPath $Map.File
    if (-not (Test-Path -LiteralPath $LayoutPath)) {
        throw "Layout file was not found: $LayoutPath"
    }
    $LayoutPaths += $LayoutPath
}

$FilesToBackup = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog
) + $LayoutPaths

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\header-document-number-0270010-$Timestamp"
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
- Moved each supported document number to the upper-right header area directly below the document title.
- Document numbers are right-aligned and bolded.
- Labels are document-appropriate: Order #, PO #, Invoice #, Credit Memo #, Return Order #, or Transfer Order #.

### Safety
- No line, extended-text, footer, recipient, sender, routing-rule, Delivery Log, SharePoint archive, or email behavior was changed.
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
    foreach ($Map in $LayoutMap) {
        $LayoutPath = Join-Path -Path $ReportLayoutFolder -ChildPath $Map.File
        Update-LayoutDocumentNumber `
            -LayoutPath $LayoutPath `
            -FieldName $Map.Field `
            -Label $Map.Label
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
    Write-Host " GPI header document number layout pass 0.27.0.10" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Layouts updated:    $($LayoutMap.Count)"
    Write-Host "Backup:             $BackupRoot"
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
    Write-Host "The header document-number build failed. Restoring modified files." -ForegroundColor Red

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
Write-Host " GPI 0.27.0.10 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production first, then tests only after production 0.27.0.10 is installed in the sandbox." -ForegroundColor Yellow
