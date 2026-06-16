report 70520 "GPI Sales Order Confirmation"
{
    Caption = 'GPI Sales Order Confirmation';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPIOrderConfirmation;

    dataset
    {
        dataitem(SalesHeader; "Sales Header")
        {
            DataItemTableView = sorting("Document Type", "No.") where("Document Type" = const(Order));
            RequestFilterFields = "No.";

            column(CompanyLogo; CompanyInfo.Picture) { }
            column(CompanyName; CompanyInfo.Name) { }
            column(CompanyAddress; CompanyInfo.Address) { }
            column(CompanyAddress2; CompanyInfo."Address 2") { }
            column(CompanyCity; CompanyInfo.City) { }
            column(CompanyState; CompanyInfo.County) { }
            column(CompanyPostCode; CompanyInfo."Post Code") { }
            column(CompanyPhone; CompanyInfo."Phone No.") { }
            column(CompanyHomePage; CompanyInfo."Home Page") { }

            column(BillToName; "Bill-to Name") { }
            column(BillToName2; "Bill-to Name 2") { }
            column(BillToAddress; "Bill-to Address") { }
            column(BillToAddress2; "Bill-to Address 2") { }
            column(BillToCity; "Bill-to City") { }
            column(BillToState; "Bill-to County") { }
            column(BillToPostCode; "Bill-to Post Code") { }
            column(BillToCountry; "Bill-to Country/Region Code") { }

            column(ShipToName; "Ship-to Name") { }
            column(ShipToName2; "Ship-to Name 2") { }
            column(ShipToAddress; "Ship-to Address") { }
            column(ShipToAddress2; "Ship-to Address 2") { }
            column(ShipToCity; "Ship-to City") { }
            column(ShipToState; "Ship-to County") { }
            column(ShipToPostCode; "Ship-to Post Code") { }
            column(ShipToCountry; "Ship-to Country/Region Code") { }

            column(ConfirmTo; "Sell-to Contact") { }
            column(OrderNo; "No.") { }
            column(OrderDate; "Order Date") { }
            column(RequestedDeliveryDate; "Requested Delivery Date") { }
            column(CustomerNo; "Sell-to Customer No.") { }
            column(CustomerPONo; "External Document No.") { }
            column(LocationCode; "Location Code") { }
            column(ShipmentMethodDescription; ShipmentMethodDescription) { }
            column(FOBText; FOBText) { }
            column(PaymentTermsDescription; PaymentTermsDescription) { }
            column(SalespersonName; SalespersonName) { }
            column(InsideSalespersonName; InsideSalespersonName) { }
            column(BackupInsideSalespersonName; BackupInsideSalespersonName) { }
            column(ContactLine; ContactLine) { }
            column(CurrencyCode; CurrencyCode) { }
            column(SubtotalAmount; Amount) { }
            column(TaxAmount; TaxAmount) { }
            column(OrderTotalAmount; "Amount Including VAT") { }

            dataitem(SalesLine; "Sales Line")
            {
                DataItemLink = "Document Type" = field("Document Type"), "Document No." = field("No.");
                DataItemTableView = sorting("Document Type", "Document No.", "Line No.");

                column(LineNo; "Line No.") { }
                column(ItemNo; "No.") { }
                column(LineDescription; Description) { }
                column(LineDescription2; "Description 2") { }
                column(LineLocationCode; "Location Code") { }
                column(UnitOfMeasureCode; "Unit of Measure Code") { }
                column(Quantity; Quantity) { }
                column(UnitPrice; "Unit Price") { }
                column(LineAmount; "Line Amount") { }
            }

            trigger OnAfterGetRecord()
            var
                PaymentTerms: Record "Payment Terms";
                ShipmentMethod: Record "Shipment Method";
                Salesperson: Record "Salesperson/Purchaser";
                InsideSalespersonCode: Code[20];
                BackupInsideSalespersonCode: Code[20];
            begin
                CalcFields(Amount, "Amount Including VAT");

                Clear(PaymentTermsDescription);
                if PaymentTerms.Get("Payment Terms Code") then
                    PaymentTermsDescription := PaymentTerms.Description;

                Clear(ShipmentMethodDescription);
                if ShipmentMethod.Get("Shipment Method Code") then
                    ShipmentMethodDescription := ShipmentMethod.Description;

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

                BuildContactLine();

                FOBText := GetFieldValue(SalesHeader, 'fob');

                CurrencyCode := "Currency Code";
                if CurrencyCode = '' then
                    CurrencyCode := GeneralLedgerSetup."LCY Code";

                TaxAmount := "Amount Including VAT" - Amount;
            end;
        }
    }

    requestpage
    {
        SaveValues = false;
    }

    rendering
    {
        layout(GPIOrderConfirmation)
        {
            Type = RDLC;
            Caption = 'GPI Sales Order Confirmation';
            Summary = 'Gamer-owned Sales Order Confirmation layout.';
            LayoutFile = 'src/reportlayout/GPISalesOrderConfirmationBranded.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
        GeneralLedgerSetup.Get();
    end;

    local procedure BuildContactLine()
    begin
        Clear(ContactLine);

        if (InsideSalespersonName <> '') and (BackupInsideSalespersonName <> '') then
            ContactLine := StrSubstNo(
                'Please contact %1 or %2 at %3 with any questions.',
                InsideSalespersonName,
                BackupInsideSalespersonName,
                CompanyInfo."Phone No.")
        else
            if InsideSalespersonName <> '' then
                ContactLine := StrSubstNo(
                    'Please contact %1 at %2 with any questions.',
                    InsideSalespersonName,
                    CompanyInfo."Phone No.")
            else
                ContactLine := StrSubstNo(
                    'Please contact Gamer Packaging at %1 with any questions.',
                    CompanyInfo."Phone No.");
    end;

    local procedure GetInsideSalespersonCode(SalesHeader: Record "Sales Header"): Code[20]
    var
        SalesHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateName: Text;
        CandidateCaption: Text;
        CandidateValue: Text;
    begin
        SalesHeaderRef.GetTable(SalesHeader);

        for FieldIndex := 1 to SalesHeaderRef.FieldCount do begin
            CandidateField := SalesHeaderRef.FieldIndex(FieldIndex);
            CandidateName := LowerCase(CandidateField.Name);
            CandidateCaption := LowerCase(CandidateField.Caption);

            if IsInsideSalespersonField(CandidateName, CandidateCaption) and
               (StrPos(CandidateName, 'backup') = 0) and
               (StrPos(CandidateCaption, 'backup') = 0)
            then begin
                CandidateValue := Format(CandidateField.Value);
                exit(CopyStr(CandidateValue, 1, 20));
            end;
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
        CandidateValue: Text;
    begin
        SalesHeaderRef.GetTable(SalesHeader);

        for FieldIndex := 1 to SalesHeaderRef.FieldCount do begin
            CandidateField := SalesHeaderRef.FieldIndex(FieldIndex);
            CandidateName := LowerCase(CandidateField.Name);
            CandidateCaption := LowerCase(CandidateField.Caption);

            if IsInsideSalespersonField(CandidateName, CandidateCaption) and
               ((StrPos(CandidateName, 'backup') > 0) or
                (StrPos(CandidateCaption, 'backup') > 0))
            then begin
                CandidateValue := Format(CandidateField.Value);
                exit(CopyStr(CandidateValue, 1, 20));
            end;
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

    local procedure GetFieldValue(SalesHeader: Record "Sales Header"; SearchText: Text): Text
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

            if (CandidateName = LowerCase(SearchText)) or (CandidateCaption = LowerCase(SearchText)) then
                exit(Format(CandidateField.Value));
        end;

        exit('');
    end;

    var
        CompanyInfo: Record "Company Information";
        GeneralLedgerSetup: Record "General Ledger Setup";
        PaymentTermsDescription: Text[100];
        ShipmentMethodDescription: Text[100];
        SalespersonName: Text[100];
        InsideSalespersonName: Text[100];
        BackupInsideSalespersonName: Text[100];
        ContactLine: Text[250];
        FOBText: Text[100];
        CurrencyCode: Code[10];
        TaxAmount: Decimal;
}
