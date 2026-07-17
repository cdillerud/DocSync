[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.5"
$ExpectedTestVersion = "0.8.0.5"
$NewProductionVersion = "0.27.0.6"
$NewTestVersion = "0.8.0.6"

$ProductionRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path $RepoRoot "bc-extension\zetadocs-replacement-tests"

$ProductionAppJson = Join-Path $ProductionRoot "app.json"
$TestAppJson = Join-Path $TestRoot "app.json"
$ChangeLog = Join-Path $ProductionRoot "CHANGELOG.md"
$BuildScript = Join-Path $RepoRoot "scripts\Prepare-GPIALTests.ps1"

$RequiredPaths = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog,
    $BuildScript
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

function Pick-AvailableObjectIds {
    param(
        [Parameter(Mandatory)][string]$RootPath,
        [Parameter(Mandatory)][int]$Count
    )

    $UsedIds = New-Object "System.Collections.Generic.HashSet[int]"

    Get-ChildItem -LiteralPath $RootPath -Recurse -File -Filter "*.al" |
        ForEach-Object {
            $Text = Get-Content -LiteralPath $_.FullName -Raw
            foreach ($Match in [regex]::Matches($Text, '(?im)^\s*(page|pageextension|table|tableextension|codeunit|report|reportextension|xmlport|query|enum|enumextension|permissionset|permissionsetextension|controladdin)\s+(\d+)\b')) {
                [void]$UsedIds.Add([int]$Match.Groups[2].Value)
            }
        }

    $Available = New-Object System.Collections.Generic.List[int]
    foreach ($Candidate in 70510..70649) {
        if (-not $UsedIds.Contains($Candidate)) {
            $Available.Add($Candidate)
            if ($Available.Count -eq $Count) {
                return [int[]]$Available.ToArray()
            }
        }
    }

    throw "Only found $($Available.Count) available object IDs, but need $Count. No files were changed."
}

function Replace-Once {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$OldText,
        [Parameter(Mandatory)][string]$NewText,
        [Parameter(Mandatory)][string]$Description
    )

    $Count = ([regex]::Matches($Content, [regex]::Escape($OldText))).Count
    if ($Count -ne 1) {
        throw "Expected exactly one occurrence for $Description, found $Count. No files were changed."
    }

    return $Content.Replace($OldText, $NewText)
}

function Add-RdlField {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$Path
    )

    if ($Content -match '<Field Name="LineExtendedText">') {
        return $Content
    }

    $FieldBlock = @'
        <Field Name="LineExtendedText">
          <DataField>LineExtendedText</DataField>
        </Field>
'@

    if ($Content -match '(?s)(        <Field Name="LineDescription2">\s*<DataField>LineDescription2</DataField>\s*</Field>)') {
        return [regex]::Replace(
            $Content,
            '(?s)(        <Field Name="LineDescription2">\s*<DataField>LineDescription2</DataField>\s*</Field>)',
            ('$1' + "`r`n" + $FieldBlock.TrimEnd()),
            1)
    }

    if ($Content -match '(?s)(        <Field Name="LineDescription">\s*<DataField>LineDescription</DataField>\s*</Field>)') {
        return [regex]::Replace(
            $Content,
            '(?s)(        <Field Name="LineDescription">\s*<DataField>LineDescription</DataField>\s*</Field>)',
            ('$1' + "`r`n" + $FieldBlock.TrimEnd()),
            1)
    }

    throw "Could not add LineExtendedText field to layout $Path because LineDescription field definition was not found. No files were changed."
}

function Update-RdlDescriptionExpression {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$Path
    )

    $ExpressionWithDesc2 = '<Value>=Fields!LineDescription.Value &amp; IIF(Fields!LineDescription2.Value="","",vbCrLf &amp; Fields!LineDescription2.Value)</Value>'
    $ExpressionWithDesc2AndExt = '<Value>=Fields!LineDescription.Value &amp; IIF(Fields!LineDescription2.Value="","",vbCrLf &amp; Fields!LineDescription2.Value) &amp; IIF(Fields!LineExtendedText.Value="","",vbCrLf &amp; Fields!LineExtendedText.Value)</Value>'

    $SimpleExpression = '<Value>=Fields!LineDescription.Value</Value>'
    $SimpleExpressionWithExt = '<Value>=Fields!LineDescription.Value &amp; IIF(Fields!LineExtendedText.Value="","",vbCrLf &amp; Fields!LineExtendedText.Value)</Value>'

    $Desc2Count = ([regex]::Matches($Content, [regex]::Escape($ExpressionWithDesc2))).Count
    $SimpleCount = ([regex]::Matches($Content, [regex]::Escape($SimpleExpression))).Count

    if ($Content -match 'Fields!LineExtendedText\.Value') {
        return $Content
    }

    if ($Desc2Count -eq 1) {
        return $Content.Replace($ExpressionWithDesc2, $ExpressionWithDesc2AndExt)
    }

    if ($SimpleCount -eq 1) {
        return $Content.Replace($SimpleExpression, $SimpleExpressionWithExt)
    }

    throw "Could not find a supported LineDescription expression in layout $Path. Desc2 matches: $Desc2Count. Simple matches: $SimpleCount. No files were changed."
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

$PatchFiles = New-Object System.Collections.Generic.List[string]

$CodeunitFolder = Join-Path $ProductionRoot "src\codeunit"
$ReportExtensionFolder = Join-Path $ProductionRoot "src\reportextension"
New-Item -ItemType Directory -Path $CodeunitFolder -Force | Out-Null
New-Item -ItemType Directory -Path $ReportExtensionFolder -Force | Out-Null

$ReportExtensionSpecs = @(
    @{ Name = "GPI Blanket Ext Text"; Report = "GPI Blanket Sales Order"; DataItem = "SalesLine"; ItemExpr = 'SalesLine."No."'; File = "GPIBlanketExtendedText.ReportExt.al" },
    @{ Name = "GPI Open Orders Ext Text"; Report = "GPI Customer Open Orders"; DataItem = "SalesLine"; ItemExpr = 'SalesLine."No."'; File = "GPICustomerOpenOrdersExtendedText.ReportExt.al" },
    @{ Name = "GPI Drop Ship PO Ext Text"; Report = "GPI Drop Ship Purchase Order"; DataItem = "PurchaseLine"; ItemExpr = 'PurchaseLine."No."'; File = "GPIDropShipPOExtendedText.ReportExt.al" },
    @{ Name = "GPI Pick Ticket Ext Text"; Report = "GPI Pick Ticket"; DataItem = "SalesLine"; ItemExpr = 'SalesLine."No."'; File = "GPIPickTicketExtendedText.ReportExt.al" },
    @{ Name = "GPI Prepay Ext Text"; Report = "GPI Prepayment Notice"; DataItem = "SalesLine"; ItemExpr = 'SalesLine."No."'; File = "GPIPrepaymentExtendedText.ReportExt.al" },
    @{ Name = "GPI Purch Cr Memo Ext Text"; Report = "GPI Purchase Credit Memo"; DataItem = "PurchaseCreditMemoLine"; ItemExpr = 'PurchaseCreditMemoLine."No."'; File = "GPIPurchaseCreditMemoExtendedText.ReportExt.al" },
    @{ Name = "GPI Purch Return Ext Text"; Report = "GPI Purchase Return Order"; DataItem = "PurchaseLine"; ItemExpr = 'PurchaseLine."No."'; File = "GPIPurchaseReturnExtendedText.ReportExt.al" },
    @{ Name = "GPI Purch Ret Pick Ext Text"; Report = "GPI Purchase Return Pick"; DataItem = "PurchaseLine"; ItemExpr = 'PurchaseLine."No."'; File = "GPIPurchaseReturnPickExtendedText.ReportExt.al" },
    @{ Name = "GPI Sales Cr Memo Ext Text"; Report = "GPI Sales Credit Memo"; DataItem = "SalesCreditMemoLine"; ItemExpr = 'SalesCreditMemoLine."No."'; File = "GPISalesCreditMemoExtendedText.ReportExt.al" },
    @{ Name = "GPI Sales Invoice Ext Text"; Report = "GPI Sales Invoice"; DataItem = "SalesInvoiceLine"; ItemExpr = 'SalesInvoiceLine."No."'; File = "GPISalesInvoiceExtendedText.ReportExt.al" },
    @{ Name = "GPI SO Confirm Ext Text"; Report = "GPI Sales Order Confirmation"; DataItem = "SalesLine"; ItemExpr = 'SalesLine."No."'; File = "GPISalesOrderConfirmationExtendedText.ReportExt.al" },
    @{ Name = "GPI Sales Return Ext Text"; Report = "GPI Sales Return Auth."; DataItem = "SalesLine"; ItemExpr = 'SalesLine."No."'; File = "GPISalesReturnAuthorizationExtendedText.ReportExt.al" },
    @{ Name = "GPI Sales Ret WH Ext Text"; Report = "GPI Sales Return WH Notice"; DataItem = "SalesLine"; ItemExpr = 'SalesLine."No."'; File = "GPISalesReturnWarehouseExtendedText.ReportExt.al" },
    @{ Name = "GPI Transfer Pick Ext Text"; Report = "GPI Transfer Pick List"; DataItem = "TransferLine"; ItemExpr = 'TransferLine."Item No."'; File = "GPITransferPickExtendedText.ReportExt.al" },
    @{ Name = "GPI Transfer Rcpt Ext Text"; Report = "GPI Transfer Receipt Notice"; DataItem = "TransferLine"; ItemExpr = 'TransferLine."Item No."'; File = "GPITransferReceiptExtendedText.ReportExt.al" },
    @{ Name = "GPI Warehouse PO Ext Text"; Report = "GPI Warehouse Purchase Order"; DataItem = "PurchaseLine"; ItemExpr = 'PurchaseLine."No."'; File = "GPIWarehousePOExtendedText.ReportExt.al" },
    @{ Name = "GPI Receiving Ext Text"; Report = "GPI Warehouse Receiving Notice"; DataItem = "PurchaseLine"; ItemExpr = 'PurchaseLine."No."'; File = "GPIWarehouseReceivingExtendedText.ReportExt.al" }
)

$NeededObjectIds = 1 + $ReportExtensionSpecs.Count
$ObjectIds = Pick-AvailableObjectIds -RootPath $ProductionRoot -Count $NeededObjectIds
$ExtendedTextMgtObjectId = $ObjectIds[0]

$ExtendedTextMgtPath = Join-Path $CodeunitFolder "GPIExtendedTextMgt.Codeunit.al"
if (Test-Path -LiteralPath $ExtendedTextMgtPath) {
    throw "GPI Extended Text Mgt. already exists at $ExtendedTextMgtPath. No files were changed."
}

$PatchFiles.Add($ExtendedTextMgtPath)

$ReportExtensionPaths = New-Object System.Collections.Generic.List[string]
for ($Index = 0; $Index -lt $ReportExtensionSpecs.Count; $Index++) {
    $Spec = $ReportExtensionSpecs[$Index]
    $ReportExtensionPath = Join-Path $ReportExtensionFolder $Spec.File
    if (Test-Path -LiteralPath $ReportExtensionPath) {
        throw "Report extension file already exists: $ReportExtensionPath. No files were changed."
    }
    $ReportExtensionPaths.Add($ReportExtensionPath)
    $PatchFiles.Add($ReportExtensionPath)
}

$LayoutFiles = @(
    "GPIBlanketSalesOrderBranded.rdl",
    "GPICustomerOpenOrderStatusBranded.rdl",
    "GPIDropShipPurchaseOrderBranded.rdl",
    "GPIPickTicket.rdl",
    "GPIPrepaymentNotice.rdl",
    "GPIPurchaseCreditMemoBranded.rdl",
    "GPIPurchaseReturnOrderBranded.rdl",
    "GPIPurchaseReturnPickTicketBranded.rdl",
    "GPISalesCreditMemoBranded.rdl",
    "GPISalesInvoiceBranded.rdl",
    "GPISalesOrderConfirmationBranded.rdl",
    "GPISalesReturnAuthorizationBranded.rdl",
    "GPISalesReturnWarehouseNotificationBranded.rdl",
    "GPITransferPickListBranded.rdl",
    "GPITransferReceiptNotificationBranded.rdl",
    "GPIWarehousePurchaseOrderBranded.rdl",
    "GPIWarehouseReceivingNoticeBranded.rdl"
) | ForEach-Object { Join-Path $ProductionRoot ("src\reportlayout\" + $_) }

foreach ($LayoutFile in $LayoutFiles) {
    if (-not (Test-Path -LiteralPath $LayoutFile)) {
        throw "Layout file was not found: $LayoutFile"
    }
    $PatchFiles.Add($LayoutFile)
}

$PatchFiles.Add($ProductionAppJson)
$PatchFiles.Add($TestAppJson)
$PatchFiles.Add($ChangeLog)

$Originals = @{}
foreach ($PatchFile in $PatchFiles) {
    if (Test-Path -LiteralPath $PatchFile) {
        $Originals[$PatchFile] = Get-Content -LiteralPath $PatchFile -Raw
    }
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $RepoRoot ".gpi-backups\extended-text-027006-$Timestamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

foreach ($ExistingFile in $Originals.Keys) {
    $RelativePath = $ExistingFile.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path $BackupRoot $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $ExistingFile -Destination $BackupPath -Force
}

$ExtendedTextMgtSource = @"
codeunit $ExtendedTextMgtObjectId "GPI Extended Text Mgt."
{
    Permissions =
        tabledata "Extended Text Header" = r,
        tabledata "Extended Text Line" = r;

    procedure GetItemExtendedText(ItemNo: Code[20]): Text
    var
        ExtendedTextHeader: Record "Extended Text Header";
        ExtendedTextLine: Record "Extended Text Line";
        ResultBuilder: TextBuilder;
        HasText: Boolean;
    begin
        if ItemNo = '' then
            exit('');

        ExtendedTextHeader.SetRange("Table Name", ExtendedTextHeader."Table Name"::Item);
        ExtendedTextHeader.SetRange("No.", ItemNo);

        if ExtendedTextHeader.FindSet() then
            repeat
                if HeaderApplies(ExtendedTextHeader) then begin
                    ExtendedTextLine.Reset();
                    ExtendedTextLine.SetRange("Table Name", ExtendedTextHeader."Table Name");
                    ExtendedTextLine.SetRange("No.", ExtendedTextHeader."No.");
                    ExtendedTextLine.SetRange("Language Code", ExtendedTextHeader."Language Code");
                    ExtendedTextLine.SetRange("Text No.", ExtendedTextHeader."Text No.");
                    if ExtendedTextLine.FindSet() then
                        repeat
                            AppendExtendedTextLine(ResultBuilder, HasText, ExtendedTextLine.Text);
                        until ExtendedTextLine.Next() = 0;
                end;
            until ExtendedTextHeader.Next() = 0;

        exit(ResultBuilder.ToText());
    end;

    local procedure HeaderApplies(ExtendedTextHeader: Record "Extended Text Header"): Boolean
    begin
        if not ExtendedTextHeader."All Language Codes" and (ExtendedTextHeader."Language Code" <> '') then
            exit(false);

        if (ExtendedTextHeader."Starting Date" <> 0D) and (ExtendedTextHeader."Starting Date" > WorkDate()) then
            exit(false);

        if (ExtendedTextHeader."Ending Date" <> 0D) and (ExtendedTextHeader."Ending Date" < WorkDate()) then
            exit(false);

        exit(true);
    end;

    local procedure AppendExtendedTextLine(var ResultBuilder: TextBuilder; var HasText: Boolean; ExtendedTextValue: Text)
    begin
        ExtendedTextValue := DelChr(ExtendedTextValue, '<>', ' ');
        if ExtendedTextValue = '' then
            exit;

        if HasText then
            ResultBuilder.AppendLine('');

        ResultBuilder.Append(ExtendedTextValue);
        HasText := true;
    end;
}
"@

$ProductionPackage = Join-Path $ProductionRoot "Gamer Packaging_GPI Sales Document Email_$NewProductionVersion.app"
$TestPackage = Join-Path $TestRoot "Gamer Packaging_GPI Sales Document Email Tests_$NewTestVersion.app"

try {
    Write-Utf8NoBom -Path $ExtendedTextMgtPath -Content $ExtendedTextMgtSource

    for ($Index = 0; $Index -lt $ReportExtensionSpecs.Count; $Index++) {
        $Spec = $ReportExtensionSpecs[$Index]
        $ObjectId = $ObjectIds[$Index + 1]
        $ReportExtensionPath = $ReportExtensionPaths[$Index]
        $ReportExtensionSource = @"
reportextension $ObjectId "$($Spec.Name)" extends "$($Spec.Report)"
{
    dataset
    {
        add($($Spec.DataItem))
        {
            column(LineExtendedText; ExtendedTextMgt.GetItemExtendedText($($Spec.ItemExpr)))
            {
            }
        }
    }

    var
        ExtendedTextMgt: Codeunit "GPI Extended Text Mgt.";
}
"@
        Write-Utf8NoBom -Path $ReportExtensionPath -Content $ReportExtensionSource
    }

    foreach ($LayoutFile in $LayoutFiles) {
        $LayoutContent = Get-Content -LiteralPath $LayoutFile -Raw
        $UpdatedLayout = Add-RdlField -Content $LayoutContent -Path $LayoutFile
        $UpdatedLayout = Update-RdlDescriptionExpression -Content $UpdatedLayout -Path $LayoutFile
        Write-Utf8NoBom -Path $LayoutFile -Content $UpdatedLayout
    }

    $ProductionApp.version = $NewProductionVersion
    $TestApp.version = $NewTestVersion
    $MainDependency[0].version = $NewProductionVersion

    Write-JsonNoBom -Value $ProductionApp -Path $ProductionAppJson
    Write-JsonNoBom -Value $TestApp -Path $TestAppJson

    $OriginalChangeLog = Get-Content -LiteralPath $ChangeLog -Raw
    $ChangeLogEntry = @"
## $NewProductionVersion

### Added
- Added a shared GPI Extended Text helper for Item Extended Text.
- Added report dataset extensions so item Extended Text is available to all item-based Gamer documents.
- Updated item-line report layouts so Extended Text prints single-spaced directly below the related line item description.

### Included documents
- Sales Order Confirmation, Prepayment Notice, Pick Ticket, Blanket Sales Order, Posted Sales Invoice, Posted Sales Credit Memo, Drop Ship Purchase Order, Warehouse Purchase Order, Warehouse Receiving Notice, Sales Return Authorization, Sales Return Warehouse Notification, Purchase Return Order, Purchase Return Pick Ticket, Transfer Pick List, Transfer Receipt Notification, and Customer Open Order Status.

### Safety
- Customer Statement is not changed because it does not print item lines.
- No email sending, recipient routing, Delivery Log, archive, Gamer Documents upload, or SharePoint link behavior was changed.
- No package is published automatically.
- Publish only to Sandbox_5_5_2026 or Sandbox_NoZetadocs_UAT unless Chad explicitly approves another environment.

"@

    if ($OriginalChangeLog -match '(?m)^# Changelog\s*$') {
        $UpdatedChangeLog = [regex]::Replace(
            $OriginalChangeLog,
            '(?m)^# Changelog\s*$',
            "# Changelog`r`n`r`n$ChangeLogEntry",
            1
        )
    }
    else {
        throw "The changelog header was not found. No files were changed."
    }

    Write-Utf8NoBom -Path $ChangeLog -Content $UpdatedChangeLog

    if (Test-Path -LiteralPath $ProductionPackage) {
        Remove-Item -LiteralPath $ProductionPackage -Force
    }

    if (Test-Path -LiteralPath $TestPackage) {
        Remove-Item -LiteralPath $TestPackage -Force
    }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " GPI Extended Text report patch 0.27.0.6" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Extended Text Mgt.: $ExtendedTextMgtObjectId"
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
    Write-Host "The Extended Text build failed. Restoring all modified files." -ForegroundColor Red

    foreach ($ExistingFile in $Originals.Keys) {
        $RelativePath = $ExistingFile.Substring($RepoRoot.Length).TrimStart('\')
        $BackupPath = Join-Path $BackupRoot $RelativePath
        Copy-Item -LiteralPath $BackupPath -Destination $ExistingFile -Force
    }

    foreach ($CreatedFile in $PatchFiles) {
        if (-not $Originals.ContainsKey($CreatedFile) -and (Test-Path -LiteralPath $CreatedFile)) {
            Remove-Item -LiteralPath $CreatedFile -Force
        }
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
Write-Host " GPI 0.27.0.6 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish both packages only to Sandbox_5_5_2026 or Sandbox_NoZetadocs_UAT, refresh the Testing panel, and run the complete test suite." -ForegroundColor Yellow
