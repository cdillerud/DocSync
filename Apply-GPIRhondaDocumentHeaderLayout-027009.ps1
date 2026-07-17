[CmdletBinding()]
param(
    [string]$RepoRoot = "C:\Users\ChadDillerud\Documents\DocSync-Zetadocs"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedProductionVersion = "0.27.0.8"
$ExpectedTestVersion = "0.8.0.8"
$NewProductionVersion = "0.27.0.9"
$NewTestVersion = "0.8.0.9"

$FooterAddressLine = "Gamer Packaging, Inc. | 100 S 5th Street, Suite 1900, Minneapolis, MN 55402"
$ProcurementTermsFooter = "All orders placed by Gamer that are not governed by a valid contract executed by Gamer shall be subject to the 'Standard Terms and Conditions for Non-Contracted Procurement' as published on our website: https://www.gamerpackaging.com/standard-terms-and-conditions-for-non-contracted-procurement/"

$ProductionRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement"
$TestRoot = Join-Path -Path $RepoRoot -ChildPath "bc-extension\zetadocs-replacement-tests"

$ProductionAppJson = Join-Path -Path $ProductionRoot -ChildPath "app.json"
$TestAppJson = Join-Path -Path $TestRoot -ChildPath "app.json"
$ChangeLog = Join-Path -Path $ProductionRoot -ChildPath "CHANGELOG.md"
$BuildScript = Join-Path -Path $RepoRoot -ChildPath "scripts\Prepare-GPIALTests.ps1"
$ReportLayoutFolder = Join-Path -Path $ProductionRoot -ChildPath "src\reportlayout"
$ReportFolder = Join-Path -Path $ProductionRoot -ChildPath "src\report"

$RequiredPaths = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog,
    $BuildScript,
    $ReportLayoutFolder,
    $ReportFolder
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

function Assert-ContainsOnce {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$Needle,
        [Parameter(Mandatory)][string]$Label
    )

    $Count = ([regex]::Matches($Content, [regex]::Escape($Needle))).Count
    if ($Count -ne 1) {
        throw "Expected exactly one occurrence of '$Needle' in $Label, but found $Count."
    }
}

function Replace-Once {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$Old,
        [Parameter(Mandatory)][string]$New,
        [Parameter(Mandatory)][string]$Label
    )

    Assert-ContainsOnce -Content $Content -Needle $Old -Label $Label
    return $Content.Replace($Old, $New)
}

function Get-LineEnding {
    param([Parameter(Mandatory)][string]$Content)

    if ($Content.Contains("`r`n")) {
        return "`r`n"
    }

    return "`n"
}

function Escape-RdlValue {
    param([Parameter(Mandatory)][string]$Value)
    return $Value.Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;')
}

function New-DetailTextboxXml {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Top,
        [Parameter(Mandatory)][string]$Left,
        [Parameter(Mandatory)][string]$Height,
        [Parameter(Mandatory)][string]$Width,
        [Parameter(Mandatory)][object[]]$Rows
    )

    $Paragraphs = New-Object System.Collections.Generic.List[string]

    foreach ($Row in $Rows) {
        $Label = Escape-RdlValue -Value ([string]$Row.Label)
        $Expression = [string]$Row.Expression
        $Paragraphs.Add(@"
              <Paragraph>
                <TextRuns>
                  <TextRun>
                    <Value>$Label </Value>
                    <Style>
                      <FontWeight>Bold</FontWeight>
                      <Color>#8C1D18</Color>
                    </Style>
                  </TextRun>
                  <TextRun>
                    <Value>$Expression</Value>
                  </TextRun>
                </TextRuns>
              </Paragraph>
"@)
    }

    $ParagraphText = $Paragraphs -join ""

    return @"
          <Textbox Name="$Name">
            <CanGrow>true</CanGrow>
            <Paragraphs>
$ParagraphText            </Paragraphs>
            <Top>$Top</Top>
            <Left>$Left</Left>
            <Height>$Height</Height>
            <Width>$Width</Width>
            <Style>
              <FontFamily>Arial</FontFamily>
              <FontSize>8pt</FontSize>
              <Border>
                <Color>#8C1D18</Color>
                <Style>Solid</Style>
                <Width>0.8pt</Width>
              </Border>
              <PaddingLeft>9pt</PaddingLeft>
              <PaddingTop>7pt</PaddingTop>
            </Style>
          </Textbox>
"@
}

function Replace-TextboxByName {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$TextboxName,
        [Parameter(Mandatory)][string]$ReplacementXml,
        [Parameter(Mandatory)][string]$LayoutName
    )

    $Pattern = '(?s)<Textbox Name="' + [regex]::Escape($TextboxName) + '">.*?</Textbox>'
    $Matches = [regex]::Matches($Content, $Pattern)
    if ($Matches.Count -ne 1) {
        throw "Expected exactly one Textbox named $TextboxName in $LayoutName, but found $($Matches.Count)."
    }

    return [regex]::Replace($Content, $Pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $ReplacementXml }, 1)
}

function New-ContactExpression {
    param(
        [Parameter(Mandatory)][string]$FirstField,
        [Parameter(Mandatory)][string]$SecondField
    )

    return '=Trim(First(Fields!' + $FirstField + '.Value,"DataSet_Result") &amp; IIF(Len(Trim(First(Fields!' + $SecondField + '.Value,"DataSet_Result"))) &gt; 0, vbCrLf &amp; First(Fields!' + $SecondField + '.Value,"DataSet_Result"), ""))'
}

function Get-ReportSectionWidth {
    param([Parameter(Mandatory)][string]$Content)

    $Match = [regex]::Match($Content, '(?s)</Body>\s*<Width>([^<]+)</Width>')
    if ($Match.Success) {
        return $Match.Groups[1].Value
    }

    return "7.8in"
}

function Set-PurchaseOrderTermsPageFooter {
    param(
        [Parameter(Mandatory)][string]$Content,
        [Parameter(Mandatory)][string]$LayoutName
    )

    $LineEnding = Get-LineEnding -Content $Content
    $FooterWidth = Get-ReportSectionWidth -Content $Content
    $Terms = Escape-RdlValue -Value $ProcurementTermsFooter
    $Address = Escape-RdlValue -Value $FooterAddressLine

    $FooterXml = @"
      <PageFooter>
        <Height>0.55in</Height>
        <PrintOnFirstPage>true</PrintOnFirstPage>
        <PrintOnLastPage>true</PrintOnLastPage>
        <ReportItems>
          <Textbox Name="GPIProcurementTermsFooter">
            <CanGrow>true</CanGrow>
            <KeepTogether>true</KeepTogether>
            <Paragraphs>
              <Paragraph>
                <TextRuns>
                  <TextRun>
                    <Value>$Terms</Value>
                    <Style>
                      <FontFamily>Arial</FontFamily>
                      <FontSize>6.5pt</FontSize>
                      <Color>#555555</Color>
                    </Style>
                  </TextRun>
                </TextRuns>
                <Style>
                  <TextAlign>Center</TextAlign>
                </Style>
              </Paragraph>
            </Paragraphs>
            <Top>0.02in</Top>
            <Left>0in</Left>
            <Height>0.34in</Height>
            <Width>$FooterWidth</Width>
            <Style>
              <Border>
                <Style>None</Style>
              </Border>
              <PaddingLeft>3pt</PaddingLeft>
              <PaddingRight>3pt</PaddingRight>
            </Style>
          </Textbox>
          <Textbox Name="GPIStandardAddressFooter">
            <CanGrow>false</CanGrow>
            <KeepTogether>true</KeepTogether>
            <Paragraphs>
              <Paragraph>
                <TextRuns>
                  <TextRun>
                    <Value>$Address</Value>
                    <Style>
                      <FontFamily>Arial</FontFamily>
                      <FontSize>7pt</FontSize>
                      <Color>#666666</Color>
                    </Style>
                  </TextRun>
                </TextRuns>
                <Style>
                  <TextAlign>Center</TextAlign>
                </Style>
              </Paragraph>
            </Paragraphs>
            <Top>0.39in</Top>
            <Left>0in</Left>
            <Height>0.14in</Height>
            <Width>$FooterWidth</Width>
            <Style>
              <Border>
                <Style>None</Style>
              </Border>
            </Style>
          </Textbox>
        </ReportItems>
        <Style>
          <Border>
            <Style>None</Style>
          </Border>
        </Style>
      </PageFooter>
"@

    $FooterXml = ($FooterXml -replace "`r?`n", $LineEnding)

    if ($Content -notmatch '(?s)<PageFooter>.*?</PageFooter>') {
        throw "Expected an existing PageFooter in $LayoutName before applying PO terms footer."
    }

    $Updated = [regex]::Replace(
        $Content,
        '(?s)\s*<PageFooter>.*?</PageFooter>',
        $LineEnding + $FooterXml,
        1)

    if (([regex]::Matches($Updated, '<PageFooter>')).Count -ne 1) {
        throw "Expected exactly one PageFooter in $LayoutName after update."
    }

    return $Updated
}

function Update-RdlStandardDetails {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Kind
    )

    $LayoutName = [System.IO.Path]::GetFileName($Path)
    $Content = Get-Content -LiteralPath $Path -Raw

    switch ($Kind) {
        'SalesOrder' {
            $LeftRows = @(
                @{ Label = 'Customer No:'; Expression = '=First(Fields!CustomerNo.Value,"DataSet_Result")' },
                @{ Label = 'Customer Contact:'; Expression = '=First(Fields!ConfirmTo.Value,"DataSet_Result")' },
                @{ Label = 'Customer PO:'; Expression = '=First(Fields!CustomerPONo.Value,"DataSet_Result")' },
                @{ Label = 'Terms:'; Expression = '=First(Fields!PaymentTermsDescription.Value,"DataSet_Result")' },
                @{ Label = 'Shipping Method:'; Expression = '=First(Fields!ShipmentMethodDescription.Value,"DataSet_Result")' },
                @{ Label = 'FOB:'; Expression = '=First(Fields!FOBText.Value,"DataSet_Result")' }
            )
            $RightRows = @(
                @{ Label = 'Order Date:'; Expression = '=Format(First(Fields!OrderDate.Value,"DataSet_Result"),"MM/dd/yy")' },
                @{ Label = 'Requested Receive By Date:'; Expression = '=IIF(Year(First(Fields!RequestedReceiveByDate.Value,"DataSet_Result"))=1,"",Format(First(Fields!RequestedReceiveByDate.Value,"DataSet_Result"),"MM/dd/yy"))' },
                @{ Label = 'Gamer Contacts:'; Expression = (New-ContactExpression -FirstField 'InsideSalespersonName' -SecondField 'BackupInsideSalespersonName') }
            )
            $Content = Replace-TextboxByName -Content $Content -TextboxName 'DetailsLeft' -ReplacementXml (New-DetailTextboxXml -Name 'DetailsLeft' -Top '2.45in' -Left '0in' -Height '1.18in' -Width '3.55in' -Rows $LeftRows) -LayoutName $LayoutName
            $Content = Replace-TextboxByName -Content $Content -TextboxName 'DetailsRight' -ReplacementXml (New-DetailTextboxXml -Name 'DetailsRight' -Top '2.45in' -Left '3.55in' -Height '1.18in' -Width '4.25in' -Rows $RightRows) -LayoutName $LayoutName
        }
        'PickTicket' {
            $LeftRows = @(
                @{ Label = 'Customer No:'; Expression = '=First(Fields!CustomerNo.Value,"DataSet_Result")' },
                @{ Label = 'Customer PO:'; Expression = '=First(Fields!CustomerPONo.Value,"DataSet_Result")' }
            )
            $RightRows = @(
                @{ Label = 'Order Date:'; Expression = '=Format(First(Fields!OrderDate.Value,"DataSet_Result"),"MM/dd/yy")' },
                @{ Label = 'Gamer Contacts:'; Expression = (New-ContactExpression -FirstField 'InsideSalespersonName' -SecondField 'BackupInsideSalespersonName') }
            )
            $Content = Replace-TextboxByName -Content $Content -TextboxName 'DetailsLeft' -ReplacementXml (New-DetailTextboxXml -Name 'DetailsLeft' -Top '2.45in' -Left '0in' -Height '0.72in' -Width '3.55in' -Rows $LeftRows) -LayoutName $LayoutName
            $Content = Replace-TextboxByName -Content $Content -TextboxName 'DetailsRight' -ReplacementXml (New-DetailTextboxXml -Name 'DetailsRight' -Top '2.45in' -Left '3.55in' -Height '0.72in' -Width '4.25in' -Rows $RightRows) -LayoutName $LayoutName
        }
        'Blanket' {
            $LeftRows = @(
                @{ Label = 'Customer No:'; Expression = '=First(Fields!CustomerNo.Value,"DataSet_Result")' },
                @{ Label = 'Customer Contact:'; Expression = '=First(Fields!ContactName.Value,"DataSet_Result")' },
                @{ Label = 'Customer PO:'; Expression = '=First(Fields!CustomerPONo.Value,"DataSet_Result")' },
                @{ Label = 'Terms:'; Expression = '=First(Fields!PaymentTermsDescription.Value,"DataSet_Result")' }
            )
            $RightRows = @(
                @{ Label = 'Order Date:'; Expression = '=Format(First(Fields!OrderDate.Value,"DataSet_Result"),"MM/dd/yy")' },
                @{ Label = 'Gamer Contacts:'; Expression = (New-ContactExpression -FirstField 'InsideSalespersonName' -SecondField 'BackupInsideSalespersonName') }
            )
            $Content = Replace-TextboxByName -Content $Content -TextboxName 'DetailsLeft' -ReplacementXml (New-DetailTextboxXml -Name 'DetailsLeft' -Top '2.34in' -Left '0in' -Height '0.95in' -Width '3.75in' -Rows $LeftRows) -LayoutName $LayoutName
            $Content = Replace-TextboxByName -Content $Content -TextboxName 'DetailsRight' -ReplacementXml (New-DetailTextboxXml -Name 'DetailsRight' -Top '2.34in' -Left '4.05in' -Height '0.95in' -Width '3.75in' -Rows $RightRows) -LayoutName $LayoutName
        }
        'PurchaseOrder' {
            $LeftRows = @(
                @{ Label = 'Vendor No.:'; Expression = '=First(Fields!VendorNo.Value,"DataSet_Result")' },
                @{ Label = 'Vendor Contact:'; Expression = '=First(Fields!VendorContact.Value,"DataSet_Result")' },
                @{ Label = 'Terms:'; Expression = '=First(Fields!PaymentTermsDescription.Value,"DataSet_Result")' },
                @{ Label = 'Shipment Method Code:'; Expression = '=First(Fields!ShipmentMethodCode.Value,"DataSet_Result")' },
                @{ Label = 'FOB:'; Expression = '=First(Fields!FOBText.Value,"DataSet_Result")' }
            )
            $RightRows = @(
                @{ Label = 'Order Date:'; Expression = '=Format(First(Fields!OrderDate.Value,"DataSet_Result"),"MM/dd/yy")' },
                @{ Label = 'Expected Receipt Date:'; Expression = '=IIF(Year(First(Fields!ExpectedReceiptDate.Value,"DataSet_Result"))=1,"",Format(First(Fields!ExpectedReceiptDate.Value,"DataSet_Result"),"MM/dd/yy"))' },
                @{ Label = 'Gamer Contacts:'; Expression = (New-ContactExpression -FirstField 'GamerContactName1' -SecondField 'GamerContactName2') }
            )
            $Content = Replace-TextboxByName -Content $Content -TextboxName 'DetailsLeft' -ReplacementXml (New-DetailTextboxXml -Name 'DetailsLeft' -Top '2.34in' -Left '0in' -Height '1.12in' -Width '3.75in' -Rows $LeftRows) -LayoutName $LayoutName
            $Content = Replace-TextboxByName -Content $Content -TextboxName 'DetailsRight' -ReplacementXml (New-DetailTextboxXml -Name 'DetailsRight' -Top '2.34in' -Left '4.05in' -Height '1.12in' -Width '3.75in' -Rows $RightRows) -LayoutName $LayoutName
            $Content = Set-PurchaseOrderTermsPageFooter -Content $Content -LayoutName $LayoutName
        }
        'ReceivingNotice' {
            $ReceiptRows = @(
                @{ Label = 'Warehouse Receipt Date:'; Expression = '=Format(First(Fields!WarehouseReceiptDate.Value,"DataSet_Result"),"MM/dd/yyyy")' },
                @{ Label = 'Order Date:'; Expression = '=Format(First(Fields!OrderDate.Value,"DataSet_Result"),"MM/dd/yy")' }
            )
            $ContactRows = @(
                @{ Label = 'Gamer Contacts:'; Expression = (New-ContactExpression -FirstField 'GamerContactName1' -SecondField 'GamerContactName2') }
            )
            $Content = Replace-TextboxByName -Content $Content -TextboxName 'ReceiptDate' -ReplacementXml (New-DetailTextboxXml -Name 'ReceiptDate' -Top '2.5in' -Left '0in' -Height '0.72in' -Width '3.75in' -Rows $ReceiptRows) -LayoutName $LayoutName
            $Content = Replace-TextboxByName -Content $Content -TextboxName 'Details' -ReplacementXml (New-DetailTextboxXml -Name 'Details' -Top '2.5in' -Left '4.05in' -Height '0.72in' -Width '3.75in' -Rows $ContactRows) -LayoutName $LayoutName
        }
        default {
            throw "Unknown layout kind: $Kind"
        }
    }

    try {
        [xml]$XmlCheck = $Content
    }
    catch {
        throw "The updated RDL XML for $LayoutName is not valid XML: $($_.Exception.Message)"
    }

    return $Content
}

function Update-BlanketReportAl {
    param([Parameter(Mandatory)][string]$Path)

    $Label = [System.IO.Path]::GetFileName($Path)
    $Content = Get-Content -LiteralPath $Path -Raw

    if ($Content -notmatch 'column\(InsideSalespersonName; InsideSalespersonName\)') {
        $Content = Replace-Once -Content $Content -Label $Label -Old '            column(SalespersonName; SalespersonName) { }' -New '            column(SalespersonName; SalespersonName) { }
            column(InsideSalespersonName; InsideSalespersonName) { }
            column(BackupInsideSalespersonName; BackupInsideSalespersonName) { }'
    }

    if ($Content -notmatch 'InsideSalespersonCode: Code\[20\];') {
        $Content = Replace-Once -Content $Content -Label $Label -Old '                Salesperson: Record "Salesperson/Purchaser";' -New '                Salesperson: Record "Salesperson/Purchaser";
                InsideSalespersonCode: Code[20];
                BackupInsideSalespersonCode: Code[20];'
    }

    $OldSalespersonBlock = @'
                Clear(SalespersonName);
                if Salesperson.Get("Salesperson Code") then
                    SalespersonName := Salesperson.Name;
                CurrencyCode := "Currency Code";
'@
    $NewSalespersonBlock = @'
                Clear(SalespersonName);
                if Salesperson.Get("Salesperson Code") then
                    SalespersonName := Salesperson.Name;

                InsideSalespersonCode := GetInsideSalespersonCode(SalesHeader);
                Clear(InsideSalespersonName);
                if (InsideSalespersonCode <> '') and Salesperson.Get(InsideSalespersonCode) then
                    InsideSalespersonName := Salesperson.Name;

                BackupInsideSalespersonCode := GetBackupInsideSalespersonCode(SalesHeader);
                Clear(BackupInsideSalespersonName);
                if (BackupInsideSalespersonCode <> '') and Salesperson.Get(BackupInsideSalespersonCode) then
                    BackupInsideSalespersonName := Salesperson.Name;

                CurrencyCode := "Currency Code";
'@
    if ($Content -notmatch 'InsideSalespersonCode := GetInsideSalespersonCode') {
        $Content = Replace-Once -Content $Content -Label $Label -Old $OldSalespersonBlock -New $NewSalespersonBlock
    }

    if ($Content -notmatch 'local procedure GetInsideSalespersonCode\(SalesHeader: Record "Sales Header"\): Code\[20\]') {
        $Procedures = @'
    local procedure GetInsideSalespersonCode(SalesHeader: Record "Sales Header"): Code[20]
    var
        SalesHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateName: Text;
        CandidateCaption: Text;
    begin
        SalesHeaderRef.GetTable(SalesHeader);
        for FieldIndex := 1 to SalesHeaderRef.FieldCount do begin
            CandidateField := SalesHeaderRef.FieldIndex(FieldIndex);
            CandidateName := LowerCase(CandidateField.Name);
            CandidateCaption := LowerCase(CandidateField.Caption);
            if IsInsideSalespersonField(CandidateName, CandidateCaption) and
               (StrPos(CandidateName, 'backup') = 0) and
               (StrPos(CandidateCaption, 'backup') = 0)
            then
                exit(CopyStr(Format(CandidateField.Value), 1, 20));
        end;
        exit('');
    end;

    local procedure GetBackupInsideSalespersonCode(SalesHeader: Record "Sales Header"): Code[20]
    var
        SalesHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateName: Text;
        CandidateCaption: Text;
    begin
        SalesHeaderRef.GetTable(SalesHeader);
        for FieldIndex := 1 to SalesHeaderRef.FieldCount do begin
            CandidateField := SalesHeaderRef.FieldIndex(FieldIndex);
            CandidateName := LowerCase(CandidateField.Name);
            CandidateCaption := LowerCase(CandidateField.Caption);
            if IsInsideSalespersonField(CandidateName, CandidateCaption) and
               ((StrPos(CandidateName, 'backup') > 0) or (StrPos(CandidateCaption, 'backup') > 0))
            then
                exit(CopyStr(Format(CandidateField.Value), 1, 20));
        end;
        exit('');
    end;

    local procedure IsInsideSalespersonField(FieldNameText: Text; FieldCaptionText: Text): Boolean
    begin
        exit(
            (StrPos(FieldNameText, 'inside salesperson') > 0) or
            (StrPos(FieldCaptionText, 'inside salesperson') > 0) or
            (StrPos(FieldNameText, 'inside sales') > 0) or
            (StrPos(FieldCaptionText, 'inside sales') > 0) or
            (StrPos(FieldNameText, 'isr') > 0) or
            (StrPos(FieldCaptionText, 'isr') > 0));
    end;

'@
        $Content = Replace-Once -Content $Content -Label $Label -Old '    local procedure BuildContactLine()' -New ($Procedures + '    local procedure BuildContactLine()')
    }

    if ($Content -notmatch 'InsideSalespersonName: Text\[100\];') {
        $Content = Replace-Once -Content $Content -Label $Label -Old '        SalespersonName: Text[100];' -New '        SalespersonName: Text[100];
        InsideSalespersonName: Text[100];
        BackupInsideSalespersonName: Text[100];'
    }

    return $Content
}

function Add-PurchaseReportFields {
    param(
        [Parameter(Mandatory)][string]$Path,
        [switch]$HasFindSalespersonCode
    )

    $Label = [System.IO.Path]::GetFileName($Path)
    $Content = Get-Content -LiteralPath $Path -Raw

    if ($Content -notmatch 'column\(ShipmentMethodCode; "Shipment Method Code"\)') {
        $Content = Replace-Once -Content $Content -Label $Label -Old '            column(ShipmentMethodDescription; ShipmentMethodDescription) { }' -New '            column(ShipmentMethodDescription; ShipmentMethodDescription) { }
            column(ShipmentMethodCode; "Shipment Method Code") { }'
    }

    if ($Content -notmatch 'column\(FOBText; FOBText\)') {
        $Content = Replace-Once -Content $Content -Label $Label -Old '            column(ContactLine; ContactLine) { }' -New '            column(ContactLine; ContactLine) { }
            column(FOBText; FOBText) { }
            column(GamerContactName1; GamerContactName1) { }
            column(GamerContactName2; GamerContactName2) { }'
    }

    if ($Content -notmatch 'GPIBuildGamerContactNames\(PurchaseHeader\);') {
        $Content = Replace-Once -Content $Content -Label $Label -Old '                ResolvePurchaserName(PurchaseHeader);

                CurrencyCode := "Currency Code";' -New '                ResolvePurchaserName(PurchaseHeader);
                GPIBuildGamerContactNames(PurchaseHeader);
                FOBText := GPIGetFieldValue(PurchaseHeader, ''fob'');

                CurrencyCode := "Currency Code";'
    }

    if ($Content -notmatch 'local procedure GPIBuildGamerContactNames\(PurchaseHeader: Record "Purchase Header"\)') {
        $ExtraFindProcedure = ''
        if (-not $HasFindSalespersonCode.IsPresent) {
            $ExtraFindProcedure = @'
    local procedure FindSalespersonCode(PurchaseHeader: Record "Purchase Header"; InsideSales: Boolean): Code[20]
    var
        PurchaseHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateIdentity: Text;
        CandidateValue: Text;
        IsInsideSalesField: Boolean;
    begin
        PurchaseHeaderRef.GetTable(PurchaseHeader);
        for FieldIndex := 1 to PurchaseHeaderRef.FieldCount do begin
            CandidateField := PurchaseHeaderRef.FieldIndex(FieldIndex);
            CandidateIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            IsInsideSalesField :=
                (StrPos(CandidateIdentity, 'inside salesperson') > 0) or
                (StrPos(CandidateIdentity, 'inside sales') > 0) or
                (StrPos(CandidateIdentity, 'isr') > 0);

            if (StrPos(CandidateIdentity, 'salesperson') > 0) and
               (StrPos(CandidateIdentity, 'backup') = 0) and
               (StrPos(CandidateIdentity, 'purchaser') = 0) and
               (IsInsideSalesField = InsideSales)
            then begin
                CandidateValue := DelChr(Format(CandidateField.Value), '<>', ' ');
                if CandidateValue <> '' then
                    exit(CopyStr(CandidateValue, 1, 20));
            end;
        end;
        exit('');
    end;

'@
        }

        $Procedures = @'
    local procedure GPIBuildGamerContactNames(PurchaseHeader: Record "Purchase Header")
    var
        Salesperson: Record "Salesperson/Purchaser";
        SalespersonCode: Code[20];
    begin
        Clear(GamerContactName1);
        Clear(GamerContactName2);

        if (PurchaseHeader."Purchaser Code" <> '') and Salesperson.Get(PurchaseHeader."Purchaser Code") then
            GPIAddGamerContactName(Salesperson.Name);

        SalespersonCode := FindSalespersonCode(PurchaseHeader, false);
        if (SalespersonCode <> '') and Salesperson.Get(SalespersonCode) then
            GPIAddGamerContactName(Salesperson.Name);

        SalespersonCode := FindSalespersonCode(PurchaseHeader, true);
        if (SalespersonCode <> '') and Salesperson.Get(SalespersonCode) then
            GPIAddGamerContactName(Salesperson.Name);
    end;

    local procedure GPIAddGamerContactName(ContactName: Text[100])
    begin
        ContactName := CopyStr(DelChr(ContactName, '<>', ' '), 1, MaxStrLen(ContactName));
        if ContactName = '' then
            exit;

        if (GamerContactName1 = ContactName) or (GamerContactName2 = ContactName) then
            exit;

        if GamerContactName1 = '' then begin
            GamerContactName1 := ContactName;
            exit;
        end;

        if GamerContactName2 = '' then
            GamerContactName2 := ContactName;
    end;

    local procedure GPIGetFieldValue(PurchaseHeader: Record "Purchase Header"; SearchText: Text): Text
    var
        PurchaseHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateName: Text;
        CandidateCaption: Text;
    begin
        PurchaseHeaderRef.GetTable(PurchaseHeader);
        for FieldIndex := 1 to PurchaseHeaderRef.FieldCount do begin
            CandidateField := PurchaseHeaderRef.FieldIndex(FieldIndex);
            CandidateName := LowerCase(CandidateField.Name);
            CandidateCaption := LowerCase(CandidateField.Caption);
            if (CandidateName = LowerCase(SearchText)) or (CandidateCaption = LowerCase(SearchText)) then
                exit(Format(CandidateField.Value));
        end;
        exit('');
    end;

'@
        $Content = Replace-Once -Content $Content -Label $Label -Old '    local procedure BuildContactLine()' -New ($ExtraFindProcedure + $Procedures + '    local procedure BuildContactLine()')
    }

    if ($Content -notmatch 'GamerContactName1: Text\[100\];') {
        $Content = Replace-Once -Content $Content -Label $Label -Old '        PurchaserName: Text[100];' -New '        PurchaserName: Text[100];
        FOBText: Text[100];
        GamerContactName1: Text[100];
        GamerContactName2: Text[100];'
    }

    return $Content
}

function Add-ReceivingReportFields {
    param([Parameter(Mandatory)][string]$Path)

    $Label = [System.IO.Path]::GetFileName($Path)
    $Content = Get-Content -LiteralPath $Path -Raw

    if ($Content -notmatch 'column\(GamerContactName1; GamerContactName1\)') {
        $Content = Replace-Once -Content $Content -Label $Label -Old '            column(PurchaserName; PurchaserName) { }
            column(ContactLine; ContactLine) { }' -New '            column(PurchaserName; PurchaserName) { }
            column(GamerContactName1; GamerContactName1) { }
            column(GamerContactName2; GamerContactName2) { }
            column(ContactLine; ContactLine) { }'
    }

    if ($Content -notmatch 'GPIBuildGamerContactNames\(PurchaseHeader\);') {
        $Content = Replace-Once -Content $Content -Label $Label -Old '                Clear(PurchaserName);
                if ("Purchaser Code" <> '''') and Purchaser.Get("Purchaser Code") then
                    PurchaserName := Purchaser.Name;

                if PurchaserName <> '''' then' -New '                Clear(PurchaserName);
                if ("Purchaser Code" <> '''') and Purchaser.Get("Purchaser Code") then
                    PurchaserName := Purchaser.Name;

                GPIBuildGamerContactNames(PurchaseHeader);

                if PurchaserName <> '''' then'
    }

    if ($Content -notmatch 'local procedure GPIBuildGamerContactNames\(PurchaseHeader: Record "Purchase Header"\)') {
        $Procedures = @'
    local procedure GPIBuildGamerContactNames(PurchaseHeader: Record "Purchase Header")
    var
        Salesperson: Record "Salesperson/Purchaser";
        SalespersonCode: Code[20];
    begin
        Clear(GamerContactName1);
        Clear(GamerContactName2);

        if (PurchaseHeader."Purchaser Code" <> '') and Salesperson.Get(PurchaseHeader."Purchaser Code") then
            GPIAddGamerContactName(Salesperson.Name);

        SalespersonCode := GPIFindSalespersonCode(PurchaseHeader, false);
        if (SalespersonCode <> '') and Salesperson.Get(SalespersonCode) then
            GPIAddGamerContactName(Salesperson.Name);

        SalespersonCode := GPIFindSalespersonCode(PurchaseHeader, true);
        if (SalespersonCode <> '') and Salesperson.Get(SalespersonCode) then
            GPIAddGamerContactName(Salesperson.Name);
    end;

    local procedure GPIAddGamerContactName(ContactName: Text[100])
    begin
        ContactName := CopyStr(DelChr(ContactName, '<>', ' '), 1, MaxStrLen(ContactName));
        if ContactName = '' then
            exit;

        if (GamerContactName1 = ContactName) or (GamerContactName2 = ContactName) then
            exit;

        if GamerContactName1 = '' then begin
            GamerContactName1 := ContactName;
            exit;
        end;

        if GamerContactName2 = '' then
            GamerContactName2 := ContactName;
    end;

    local procedure GPIFindSalespersonCode(PurchaseHeader: Record "Purchase Header"; InsideSales: Boolean): Code[20]
    var
        PurchaseHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateIdentity: Text;
        CandidateValue: Text;
        IsInsideSalesField: Boolean;
    begin
        PurchaseHeaderRef.GetTable(PurchaseHeader);
        for FieldIndex := 1 to PurchaseHeaderRef.FieldCount do begin
            CandidateField := PurchaseHeaderRef.FieldIndex(FieldIndex);
            CandidateIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            IsInsideSalesField :=
                (StrPos(CandidateIdentity, 'inside salesperson') > 0) or
                (StrPos(CandidateIdentity, 'inside sales') > 0) or
                (StrPos(CandidateIdentity, 'isr') > 0);

            if (StrPos(CandidateIdentity, 'salesperson') > 0) and
               (StrPos(CandidateIdentity, 'backup') = 0) and
               (StrPos(CandidateIdentity, 'purchaser') = 0) and
               (IsInsideSalesField = InsideSales)
            then begin
                CandidateValue := DelChr(Format(CandidateField.Value), '<>', ' ');
                if CandidateValue <> '' then
                    exit(CopyStr(CandidateValue, 1, 20));
            end;
        end;
        exit('');
    end;

'@
        $Content = Replace-Once -Content $Content -Label $Label -Old '    var
        CompanyInfo: Record "Company Information";' -New ($Procedures + '    var
        CompanyInfo: Record "Company Information";')
    }

    if ($Content -notmatch 'GamerContactName1: Text\[100\];') {
        $Content = Replace-Once -Content $Content -Label $Label -Old '        PurchaserName: Text[100];' -New '        PurchaserName: Text[100];
        GamerContactName1: Text[100];
        GamerContactName2: Text[100];'
    }

    return $Content
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

$Files = @{
    BlanketReport = Join-Path -Path $ReportFolder -ChildPath "GPIBlanketSalesOrder.Report.al"
    DropShipReport = Join-Path -Path $ReportFolder -ChildPath "GPIDropShipPurchaseOrder.Report.al"
    WarehousePOReport = Join-Path -Path $ReportFolder -ChildPath "GPIWarehousePurchaseOrder.Report.al"
    ReceivingReport = Join-Path -Path $ReportFolder -ChildPath "GPIWarehouseReceivingNotice.Report.al"
    SOLayout = Join-Path -Path $ReportLayoutFolder -ChildPath "GPISalesOrderConfirmationBranded.rdl"
    PrepayLayout = Join-Path -Path $ReportLayoutFolder -ChildPath "GPIPrepaymentNotice.rdl"
    PickLayout = Join-Path -Path $ReportLayoutFolder -ChildPath "GPIPickTicket.rdl"
    BlanketLayout = Join-Path -Path $ReportLayoutFolder -ChildPath "GPIBlanketSalesOrderBranded.rdl"
    DropShipLayout = Join-Path -Path $ReportLayoutFolder -ChildPath "GPIDropShipPurchaseOrderBranded.rdl"
    WarehousePOLayout = Join-Path -Path $ReportLayoutFolder -ChildPath "GPIWarehousePurchaseOrderBranded.rdl"
    ReceivingLayout = Join-Path -Path $ReportLayoutFolder -ChildPath "GPIWarehouseReceivingNoticeBranded.rdl"
}

foreach ($Key in $Files.Keys) {
    if (-not (Test-Path -LiteralPath $Files[$Key])) {
        throw "Required file was not found: $($Files[$Key])"
    }
}

$FilesToBackup = @(
    $ProductionAppJson,
    $TestAppJson,
    $ChangeLog
) + @($Files.Values)

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path -Path $RepoRoot -ChildPath ".gpi-backups\rhonda-document-header-layout-027009-$Timestamp"
New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null

foreach ($Path in $FilesToBackup) {
    $RelativePath = $Path.Substring($RepoRoot.Length).TrimStart('\')
    $BackupPath = Join-Path -Path $BackupRoot -ChildPath $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $BackupPath) -Force | Out-Null
    Copy-Item -LiteralPath $Path -Destination $BackupPath -Force
}

$UpdatedTextFiles = @{}

$UpdatedTextFiles[$Files.BlanketReport] = Update-BlanketReportAl -Path $Files.BlanketReport
$UpdatedTextFiles[$Files.DropShipReport] = Add-PurchaseReportFields -Path $Files.DropShipReport -HasFindSalespersonCode
$UpdatedTextFiles[$Files.WarehousePOReport] = Add-PurchaseReportFields -Path $Files.WarehousePOReport -HasFindSalespersonCode
$UpdatedTextFiles[$Files.ReceivingReport] = Add-ReceivingReportFields -Path $Files.ReceivingReport

$UpdatedTextFiles[$Files.SOLayout] = Update-RdlStandardDetails -Path $Files.SOLayout -Kind 'SalesOrder'
$UpdatedTextFiles[$Files.PrepayLayout] = Update-RdlStandardDetails -Path $Files.PrepayLayout -Kind 'SalesOrder'
$UpdatedTextFiles[$Files.PickLayout] = Update-RdlStandardDetails -Path $Files.PickLayout -Kind 'PickTicket'
$UpdatedTextFiles[$Files.BlanketLayout] = Update-RdlStandardDetails -Path $Files.BlanketLayout -Kind 'Blanket'
$UpdatedTextFiles[$Files.DropShipLayout] = Update-RdlStandardDetails -Path $Files.DropShipLayout -Kind 'PurchaseOrder'
$UpdatedTextFiles[$Files.WarehousePOLayout] = Update-RdlStandardDetails -Path $Files.WarehousePOLayout -Kind 'PurchaseOrder'
$UpdatedTextFiles[$Files.ReceivingLayout] = Update-RdlStandardDetails -Path $Files.ReceivingLayout -Kind 'ReceivingNotice'

$ProductionApp.version = $NewProductionVersion
$TestApp.version = $NewTestVersion
$MainDependency[0].version = $NewProductionVersion

$ChangeLogOriginal = Get-Content -LiteralPath $ChangeLog -Raw
$ChangeLogEntry = @"
## $NewProductionVersion

### Changed
- Reworked the Sales Order Confirmation, Warehouse Pick Instruction, Prepayment Notice, Blanket Sales Order, Drop Ship Purchase Order, Warehouse Purchase Order, and Warehouse Receiving Notice header detail blocks to match Rhonda's approved layout standard.
- Sales customer-facing detail blocks now group Customer No., Customer Contact, Customer PO, Terms, Shipping Method, and FOB on the left, with Order Date, Requested Receive By Date, and Gamer Contacts on the right where applicable.
- Warehouse Pick Instruction now shows Customer No. and Customer PO on the left, with Order Date and Gamer Contacts on the right.
- Blanket Sales Order now shows Customer No., Customer Contact, Customer PO, and Terms on the left, with Order Date and Gamer Contacts on the right.
- Purchase Order detail blocks now show Vendor No., Vendor Contact, Terms, Shipment Method Code, and FOB on the left, with Order Date, Expected Receipt Date, and Gamer Contacts on the right.
- Warehouse Receiving Notice now shows Warehouse Receipt Date and Order Date on the left, with Gamer Contacts on the right.
- Drop Ship and Warehouse Purchase Order footers now include the non-contracted procurement terms language plus the Gamer address line at the bottom of the page.

### Safety
- No extended-text, line visibility, recipient, sender, routing-rule, Delivery Log, SharePoint archive, or email behavior was changed.
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
    foreach ($Path in $UpdatedTextFiles.Keys) {
        Write-Utf8NoBom -Path $Path -Content $UpdatedTextFiles[$Path]
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
    Write-Host " GPI Rhonda document header layout pass 0.27.0.9" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "Production version: $NewProductionVersion"
    Write-Host "Test version:       $NewTestVersion"
    Write-Host "Files updated:      $($UpdatedTextFiles.Count) plus app.json/changelog"
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
    Write-Host "The Rhonda document header layout build failed. Restoring modified files." -ForegroundColor Red

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
Write-Host " GPI 0.27.0.9 build passed" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Production package: $ProductionPackage"
Write-Host "Test package:       $TestPackage"
Write-Host "Backup:             $BackupRoot"
Write-Host ""
Write-Host "No package was published." -ForegroundColor Yellow
Write-Host "Publish production 0.27.0.9 first, then tests 0.8.0.9 only after production is installed in the sandbox." -ForegroundColor Yellow
