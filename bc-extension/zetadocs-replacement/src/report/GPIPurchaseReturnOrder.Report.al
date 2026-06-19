report 70560 "GPI Purchase Return Order"
{
    Caption = 'GPI Purchase Return Order';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPIPurchaseReturnOrder;

    dataset
    {
        dataitem(PurchaseHeader; "Purchase Header")
        {
            DataItemTableView = sorting("Document Type", "No.") where("Document Type" = const("Return Order"));
            RequestFilterFields = "No.";

            column(CompanyLogo; CompanyInfo.Picture) { }
            column(CompanyName; CompanyInfo.Name) { }
            column(CompanyAddressLine; CompanyAddressLine) { }
            column(CompanyPhone; CompanyInfo."Phone No.") { }
            column(VendorName; "Buy-from Vendor Name") { }
            column(VendorAddressLine; VendorAddressLine) { }
            column(VendorContact; "Buy-from Contact") { }
            column(ReturnOrderNo; "No.") { }
            column(OrderDate; "Order Date") { }
            column(PostingDate; "Posting Date") { }
            column(VendorNo; "Buy-from Vendor No.") { }
            column(YourReference; "Your Reference") { }
            column(LocationCode; "Location Code") { }
            column(OutsideSalespersonName; OutsideSalespersonName) { }
            column(InsideSalespersonName; InsideSalespersonName) { }
            column(ContactLine; ContactLine) { }

            dataitem(PurchaseLine; "Purchase Line")
            {
                DataItemLink = "Document Type" = field("Document Type"), "Document No." = field("No.");
                DataItemTableView = sorting("Document Type", "Document No.", "Line No.");

                column(ItemNo; "No.") { }
                column(VendorItemNo; "Vendor Item No.") { }
                column(LineDescription; Description) { }
                column(LineDescription2; "Description 2") { }
                column(Quantity; Quantity) { }
                column(UnitOfMeasureCode; "Unit of Measure Code") { }
                column(ReturnReasonCode; "Return Reason Code") { }

                trigger OnPreDataItem()
                begin
                    SetFilter("No.", '<>%1', '');
                end;

                trigger OnAfterGetRecord()
                begin
                    if not LineVisibilityMgt.ShouldPrintPurchaseLine(PurchaseLine, false) then
                        CurrReport.Skip();
                end;
            }

            trigger OnAfterGetRecord()
            begin
                LineVisibilityMgt.ValidatePurchaseExternalDocument(PurchaseHeader);
                CompanyAddressLine := BuildAddressLine(
                    CompanyInfo.Address,
                    CompanyInfo."Address 2",
                    CompanyInfo.City,
                    CompanyInfo.County,
                    CompanyInfo."Post Code");
                VendorAddressLine := BuildAddressLine(
                    "Buy-from Address",
                    "Buy-from Address 2",
                    "Buy-from City",
                    "Buy-from County",
                    "Buy-from Post Code");
                ResolveSalespeople(PurchaseHeader);
                BuildContactLine();
            end;
        }
    }

    requestpage
    {
        SaveValues = false;
    }

    rendering
    {
        layout(GPIPurchaseReturnOrder)
        {
            Type = RDLC;
            Caption = 'GPI Purchase Return Order';
            Summary = 'Vendor-facing Gamer Purchase Return Order.';
            LayoutFile = 'src/reportlayout/GPIPurchaseReturnOrderBranded.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
    end;

    local procedure ResolveSalespeople(PurchaseHeader: Record "Purchase Header")
    var
        Salesperson: Record "Salesperson/Purchaser";
        SalespersonCode: Code[20];
    begin
        Clear(OutsideSalespersonName);
        Clear(InsideSalespersonName);

        SalespersonCode := FindSalespersonCode(PurchaseHeader, false);
        if (SalespersonCode <> '') and Salesperson.Get(SalespersonCode) then
            OutsideSalespersonName := Salesperson.Name;

        SalespersonCode := FindSalespersonCode(PurchaseHeader, true);
        if (SalespersonCode <> '') and Salesperson.Get(SalespersonCode) then
            InsideSalespersonName := Salesperson.Name;
    end;

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

    local procedure BuildAddressLine(Address: Text; Address2: Text; City: Text; State: Text; PostCode: Text): Text
    var
        Result: Text;
    begin
        Result := Address;
        if Address2 <> '' then
            Result += ' ' + Address2;
        if City <> '' then begin
            if Result <> '' then
                Result += ', ';
            Result += City;
        end;
        if State <> '' then
            Result += ', ' + State;
        if PostCode <> '' then
            Result += ' ' + PostCode;
        exit(Result);
    end;

    local procedure BuildContactLine()
    begin
        if InsideSalespersonName <> '' then
            ContactLine := StrSubstNo(
                'Please contact %1 at %2 with questions about this purchase return.',
                InsideSalespersonName,
                CompanyInfo."Phone No.")
        else
            ContactLine := StrSubstNo(
                'Please contact Gamer Packaging at %1 with questions about this purchase return.',
                CompanyInfo."Phone No.");
    end;

    var
        CompanyInfo: Record "Company Information";
        LineVisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        CompanyAddressLine: Text[250];
        VendorAddressLine: Text[250];
        OutsideSalespersonName: Text[100];
        InsideSalespersonName: Text[100];
        ContactLine: Text[250];
}
