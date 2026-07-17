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

function Get-BodyWidth {
    param([Parameter(Mandatory)][string]$Content)

    $Match = [regex]::Match($Content, '(?s)<Body\b[^>]*>.*?<Width>([0-9.]+)in</Width>')
    if ($Match.Success) {
        return Convert-InchTextToDecimal $Match.Groups[1].Value
    }

    return 7.8
}

function Get-TitlePlacement {
    param([Parameter(Mandatory)][string]$Content)

    $BodyWidth = Get-BodyWidth -Content $Content
    $DefaultWidth = 2.6
    $Placement = [ordered]@{
        Top = 0.76
        Left = [Math]::Max(0, $BodyWidth - $DefaultWidth)
        Width = $DefaultWidth
    }

    $TitleMatch = [regex]::Match($Content, '(?s)<Textbox\s+Name="TitleBox">.*?</Textbox>')
    if (-not $TitleMatch.Success) {
        $TitleMatch = [regex]::Match($Content, '(?s)<Textbox\s+Name="(Title|DocumentTitle|ReportTitle)">.*?</Textbox>')
    }

    if ($TitleMatch.Success) {
        $TitleBlock = $TitleMatch.Value
        $TitleTop = Get-TagInches -Xml $TitleBlock -TagName "Top"
        $TitleLeft = Get-TagInches -Xml $TitleBlock -TagName "Left"
        $TitleHeight = Get-TagInches -Xml $TitleBlock -TagName "Height"
        $TitleWidth = Get-TagInches -Xml $TitleBlock -TagName "Width"

        if ($TitleTop + $TitleHeight -gt 0) {
            $Placement.Top = $TitleTop + $TitleHeight + 0.03
        }

        if ($TitleLeft -gt 0) {
            $Placement.Left = $TitleLeft
        }

        if ($TitleWidth -gt 0) {
            $Placement.Width = $TitleWidth
        }
    }

    return $Placement
}

function New-HeaderDocumentNumberTextboxXml {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string]$FieldName,
        [Parameter(Mandatory)][string]$Top,
        [Parameter(Mandatory)][string]$Left,
        [Parameter(Mandatory)][string]$Width,
        [Parameter(Mandatory)][string]$LineEnding
    )

    $Expression = '="' + $Label + ': " &amp; First(Fields!' + $FieldName + '.Value,"DataSet_Result")'

    $Xml = @"
          <Textbox Name="GPIHeaderDocumentNumber">
            <CanGrow>false</CanGrow>
            <KeepTogether>true</KeepTogether>
            <Paragraphs>
              <Paragraph>
                <TextRuns>
                  <TextRun>
                    <Value>$Expression</Value>
                    <Style>
                      <FontFamily>Arial</FontFamily>
                      <FontSize>10pt</FontSize>
                      <FontWeight>Bold</FontWeight>
                      <Color>#555555</Color>
                    </Style>
                  </TextRun>
                </TextRuns>
                <Style>
                  <TextAlign>Right</TextAlign>
                </Style>
              </Paragraph>
            </Paragraphs>
            <Top>$Top</Top>
            <Left>$Left</Left>
            <Height>0.22in</Height>
            <Width>$Width</Width>
            <Style>
              <Border>
                <Style>None</Style>
              </Border>
            </Style>
          </Textbox>
"@

    return ($Xml -replace "`r?`n", $LineEnding)
}

function Remove-ExistingHeaderDocumentNumberBox {
    param([Parameter(Mandatory)][string]$Content)

    return [regex]::Replace(
        $Content,
        '(?s)\s*<Textbox\s+Name="GPIHeaderDocumentNumber">.*?</Textbox>',
        '',
        1)
}

function Insert-HeaderDocumentNumberBox {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$TextboxXml,
        [Parameter(Mandatory)][string]$LayoutName
    )

    $TitleMatch = [regex]::Match($Content, '(?s)<Textbox\s+Name="TitleBox">.*?</Textbox>')
    if (-not $TitleMatch.Success) {
        $TitleMatch = [regex]::Match($Content, '(?s)<Textbox\s+Name="(Title|DocumentTitle|ReportTitle)">.*?</Textbox>')
    }

    if ($TitleMatch.Success) {
        $InsertAt = $TitleMatch.Index + $TitleMatch.Length
        return $Content.Substring(0, $InsertAt) + (Get-LineEnding -Content $Content) + $TextboxXml + $Content.Substring($InsertAt)
    }

    $ReportItemsMatch = [regex]::Match($Content, '(?s)<ReportItems>\s*')
    if (-not $ReportItemsMatch.Success) {
        throw "Could not find ReportItems in $LayoutName."
    }

    $InsertAt = $ReportItemsMatch.Index + $ReportItemsMatch.Length
    return $Content.Substring(0, $InsertAt) + (Get-LineEnding -Content $Content) + $TextboxXml + $Content.Substring($InsertAt)
}

function Update-LayoutHeaderDocumentNumber {
    param(
        [Parameter(Mandatory)][string]$LayoutPath,
        [Parameter(Mandatory)][string]$FieldName,
        [Parameter(Mandatory)][string]$Label
    )

    $LayoutName = [System.IO.Path]::GetFileName($LayoutPath)
    $Content = Get-Content -LiteralPath $LayoutPath -Raw
    $LineEnding = Get-LineEnding -Content $Content

    if ($Content -notmatch [regex]::Escape("Fields!$FieldName.Value")) {
        Write-Host "Warning: $LayoutName does not currently reference Fields!$FieldName.Value in a visible textbox. Adding a header textbox that references the report dataset field." -ForegroundColor Yellow
    }

    $Placement = Get-TitlePlacement -Content $Content

    $TextboxXml = New-HeaderDocumentNumberTextboxXml `
        -Label $Label `
        -FieldName $FieldName `
        -Top (Format-Inches ([double]$Placement.Top)) `
        -Left (Format-Inches ([double]$Placement.Left)) `
        -Width (Format-Inches ([double]$Placement.Width)) `
        -LineEnding $LineEnding

    $Updated = Remove-ExistingHeaderDocumentNumberBox -Content $Content
    $Updated = Insert-HeaderDocumentNumberBox -Content $Updated -TextboxXml $TextboxXml -LayoutName $LayoutName

    try {
        [xml]$XmlCheck = $Updated
    }
    catch {
        throw "The updated RDL XML for $LayoutName is not valid XML: $($_.Exception.Message)"
    }

    if (([regex]::Matches($Updated, '<Textbox\s+Name="GPIHeaderDocumentNumber">')).Count -ne 1) {
        throw "Expected exactly one GPIHeaderDocumentNumber textbox in $LayoutName after update."
    }

    if ($Updated -notmatch [regex]::Escape("Fields!$FieldName.Value")) {
        throw "Header document number field $FieldName was not added to $LayoutName."
    }

    if ($Updated -notmatch '<FontWeight>Bold</FontWeight>') {
        throw "Bold document number formatting was not added to $LayoutName."
    }

    Write-Utf8NoBom -Path $LayoutPath -Content $Updated

    return [pscustomobject]@{
        Layout = $LayoutName
        Field = $FieldName
        Label = $Label
        Top = Format-Inches ([double]$Placement.Top)
        Left = Format-Inches ([double]$Placement.Left)
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
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\header-document-number-0270010-v3-$Timestamp"
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
- Added a bold document-number line under the upper-right document title on supported document layouts.
- Labels are document-appropriate: Order #, PO #, Invoice #, Credit Memo #, Return Order #, or Transfer Order #.
- This v3 patch inserts a dedicated RDLC header textbox in schema-safe element order instead of trying to move or rewrite existing detail textboxes.

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
    $MoveResults = @()
    foreach ($Map in $LayoutMap) {
        $LayoutPath = Join-Path -Path $ReportLayoutFolder -ChildPath $Map.File
        $MoveResults += Update-LayoutHeaderDocumentNumber `
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
    Write-Host " GPI header document number layout pass 0.27.0.10 v3" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Layouts updated:    $($MoveResults.Count)"
    Write-Host "Backup:             $BackupRoot"
    Write-Host ""

    foreach ($Result in $MoveResults) {
        Write-Host ("{0}: {1} / {2} at top {3}, left {4}" -f $Result.Layout, $Result.Label, $Result.Field, $Result.Top, $Result.Left)
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
