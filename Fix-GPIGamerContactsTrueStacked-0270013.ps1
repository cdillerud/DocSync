[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.12"
$ExpectedTestVersion = "0.8.0.12"
$NewProductionVersion = "0.27.0.13"
$NewTestVersion = "0.8.0.13"

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

function New-RdlElement {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][string]$LocalName
    )

    return $Doc.CreateElement($LocalName, $Doc.DocumentElement.NamespaceURI)
}

function Append-TextElement {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Parent,
        [Parameter(Mandatory)][string]$LocalName,
        [Parameter(Mandatory)][string]$Value
    )

    $Element = New-RdlElement -Doc $Doc -LocalName $LocalName
    $Element.InnerText = $Value
    [void]$Parent.AppendChild($Element)
    return $Element
}

function New-TextRun {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][string]$Value,
        [string]$FontWeight = "",
        [string]$Color = "",
        [string]$FontFamily = "",
        [string]$FontSize = ""
    )

    $TextRun = New-RdlElement -Doc $Doc -LocalName "TextRun"
    [void](Append-TextElement -Doc $Doc -Parent $TextRun -LocalName "Value" -Value $Value)

    if (($FontWeight -ne "") -or ($Color -ne "") -or ($FontFamily -ne "") -or ($FontSize -ne "")) {
        $Style = New-RdlElement -Doc $Doc -LocalName "Style"

        if ($FontFamily -ne "") {
            [void](Append-TextElement -Doc $Doc -Parent $Style -LocalName "FontFamily" -Value $FontFamily)
        }

        if ($FontSize -ne "") {
            [void](Append-TextElement -Doc $Doc -Parent $Style -LocalName "FontSize" -Value $FontSize)
        }

        if ($FontWeight -ne "") {
            [void](Append-TextElement -Doc $Doc -Parent $Style -LocalName "FontWeight" -Value $FontWeight)
        }

        if ($Color -ne "") {
            [void](Append-TextElement -Doc $Doc -Parent $Style -LocalName "Color" -Value $Color)
        }

        [void]$TextRun.AppendChild($Style)
    }

    return $TextRun
}

function New-Paragraph {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement[]]$TextRuns,
        [ValidateSet("Left","Center","Right")][string]$TextAlign = "Left"
    )

    $Paragraph = New-RdlElement -Doc $Doc -LocalName "Paragraph"
    $TextRunsElement = New-RdlElement -Doc $Doc -LocalName "TextRuns"

    foreach ($TextRun in $TextRuns) {
        [void]$TextRunsElement.AppendChild($TextRun)
    }

    [void]$Paragraph.AppendChild($TextRunsElement)

    $Style = New-RdlElement -Doc $Doc -LocalName "Style"
    [void](Append-TextElement -Doc $Doc -Parent $Style -LocalName "TextAlign" -Value $TextAlign)
    [void]$Paragraph.AppendChild($Style)

    return $Paragraph
}

function Convert-ExpressionToNoLabel {
    param([Parameter(Mandatory)][string]$Expression)

    $Expr = $Expression.Trim()

    if (-not $Expr.StartsWith("=")) {
        return $Expr
    }

    # Remove an embedded literal label when the old layout used a single expression.
    $Expr = [regex]::Replace($Expr, '=\s*"Gamer Contacts:\s*"\s*&\s*', '=', 1)
    $Expr = [regex]::Replace($Expr, '=\s*Trim\(\s*"Gamer Contacts:\s*"\s*&\s*', '=Trim(', 1)

    # If a previous patch prefixed the first returned contact with vbCrLf, remove that first line break.
    $Expr = [regex]::Replace($Expr, ',\s*vbCrLf\s*&\s*First\(Fields!', ', First(Fields!', 1)

    return $Expr
}

function Get-ContactExpression {
    param(
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $Expressions = New-Object System.Collections.Generic.List[string]
    $ValueNodes = @($Textbox.SelectNodes(".//rdl:TextRun/rdl:Value", $NsMgr))

    foreach ($ValueNode in $ValueNodes) {
        $Text = ([string]$ValueNode.InnerText).Trim()

        if (-not $Text.StartsWith("=")) {
            continue
        }

        $Expr = Convert-ExpressionToNoLabel -Expression $Text

        if ($Expr -match 'Fields!.*Contact.*\.Value' -or $Expr -match 'GamerContactName' -or $Expr -match 'SalespersonName') {
            [void]$Expressions.Add($Expr)
        }
    }

    if ($Expressions.Count -eq 1) {
        return $Expressions[0]
    }

    if ($Expressions.Count -gt 1) {
        $Parts = @()
        foreach ($Expr in $Expressions) {
            $Parts += $Expr.Substring(1)
        }

        $Combined = "=Trim("
        for ($Index = 0; $Index -lt $Parts.Count; $Index++) {
            $Part = $Parts[$Index]
            if ($Index -eq 0) {
                $Combined += $Part
            }
            else {
                $Combined += ' & IIF(Len(Trim(' + $Part + ')) > 0, vbCrLf & ' + $Part + ', "")'
            }
        }
        $Combined += ")"

        return $Combined
    }

    return ""
}

function Replace-GamerContactsParagraphs {
    param(
        [Parameter(Mandatory)][System.Xml.XmlDocument]$Doc,
        [Parameter(Mandatory)][System.Xml.XmlElement]$Textbox,
        [Parameter(Mandatory)][System.Xml.XmlNamespaceManager]$NsMgr
    )

    $OldParagraphs = $Textbox.SelectSingleNode("rdl:Paragraphs", $NsMgr)
    if ($null -eq $OldParagraphs) {
        return $false
    }

    $ContactExpression = Get-ContactExpression -Textbox $Textbox -NsMgr $NsMgr
    if ([string]::IsNullOrWhiteSpace($ContactExpression)) {
        return $false
    }

    $NewParagraphs = New-RdlElement -Doc $Doc -LocalName "Paragraphs"

    $LabelRun = New-TextRun `
        -Doc $Doc `
        -Value "Gamer Contacts:" `
        -FontWeight "Bold" `
        -Color "#8C1D18"

    $ContactsRun = New-TextRun `
        -Doc $Doc `
        -Value $ContactExpression

    $LabelParagraph = New-Paragraph `
        -Doc $Doc `
        -TextRuns @($LabelRun) `
        -TextAlign "Left"

    $ContactsParagraph = New-Paragraph `
        -Doc $Doc `
        -TextRuns @($ContactsRun) `
        -TextAlign "Left"

    [void]$NewParagraphs.AppendChild($LabelParagraph)
    [void]$NewParagraphs.AppendChild($ContactsParagraph)

    [void]$Textbox.ReplaceChild($NewParagraphs, $OldParagraphs)

    # If CanGrow already exists, set it true. Do not append a new CanGrow because element order matters in RDL.
    $CanGrowNode = $Textbox.SelectSingleNode("rdl:CanGrow", $NsMgr)
    if ($null -ne $CanGrowNode) {
        $CanGrowNode.InnerText = "true"
    }

    $HeightNode = $Textbox.SelectSingleNode("rdl:Height", $NsMgr)
    if ($null -ne $HeightNode) {
        $HeightText = [string]$HeightNode.InnerText
        $HeightValue = 0.0
        [void][double]::TryParse(
            $HeightText.Replace("in", ""),
            [System.Globalization.NumberStyles]::Float,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [ref]$HeightValue)

        if (($HeightValue -gt 0) -and ($HeightValue -lt 0.78)) {
            $HeightNode.InnerText = "0.82in"
        }
    }

    return $true
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

function Update-GamerContactsLayout {
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

    $NsMgr = New-Object System.Xml.XmlNamespaceManager($Doc.NameTable)
    [void]$NsMgr.AddNamespace("rdl", $Doc.DocumentElement.NamespaceURI)

    $Textboxes = @($Doc.SelectNodes("//rdl:Textbox[not(ancestor::rdl:Tablix)]", $NsMgr))
    $Changed = 0

    foreach ($TextboxNode in $Textboxes) {
        $Textbox = [System.Xml.XmlElement]$TextboxNode
        $Text = [string]$Textbox.InnerText

        if ($Text -match 'Gamer Contacts') {
            if (Replace-GamerContactsParagraphs -Doc $Doc -Textbox $Textbox -NsMgr $NsMgr) {
                $Changed++
            }
        }
    }

    if ($Changed -gt 0) {
        Save-XmlDocumentUtf8NoBom -Doc $Doc -Path $LayoutPath

        try {
            [xml]$XmlCheck = Get-Content -LiteralPath $LayoutPath -Raw
        }
        catch {
            throw "The updated RDL XML for $LayoutName is not valid XML after save: $($_.Exception.Message)"
        }
    }

    $Updated = Get-Content -LiteralPath $LayoutPath -Raw

    return [pscustomobject]@{
        Layout = $LayoutName
        BlocksFixed = $Changed
        Changed = ($Updated -ne $Original)
    }
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
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\gamer-contacts-stacked-0270013-$Timestamp"
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

### Fixed
- Gamer Contacts now render as a true two-paragraph block:
  Gamer Contacts:
  Contact Name 1
  Contact Name 2
- The first contact is no longer inline after the label.

### Safety
- No dataset fields, line-grid formatting, decimals, footer text, recipient logic, sender logic, routing rules, Delivery Log, SharePoint archive, or email behavior was changed.
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
        $Results += Update-GamerContactsLayout -LayoutPath $LayoutFile
    }

    $ChangedCount = @($Results | Where-Object { $_.Changed }).Count
    $BlockCount = 0
    foreach ($Result in $Results) {
        $BlockCount += [int]$Result.BlocksFixed
    }

    if ($BlockCount -eq 0) {
        throw "No Gamer Contacts blocks were found to update. No files were changed."
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
    Write-Host " GPI Gamer Contacts true stacked layout pass 0.27.0.13" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Layouts scanned:    $($Results.Count)"
    Write-Host "Layouts changed:    $ChangedCount"
    Write-Host "Blocks fixed:       $BlockCount"
    Write-Host "Backup:             $BackupRoot"
    Write-Host ""

    foreach ($Result in $Results) {
        if ($Result.BlocksFixed -gt 0) {
            Write-Host ("{0}: Gamer Contacts blocks fixed={1}" -f $Result.Layout, $Result.BlocksFixed)
        }
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
    Write-Host "The Gamer Contacts true stacked layout build failed. Restoring modified files." -ForegroundColor Red

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
Write-Host " GPI 0.27.0.13 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production first, then tests only after production 0.27.0.13 is installed in the sandbox." -ForegroundColor Yellow
