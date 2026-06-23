report 70521 "GPI Prepayment Notice"
{
    Caption = 'GPI Prepayment Notice';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPIPrepaymentNotice;

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
            column(RequestedReceiveByDate; RequestedReceiveByDate) { }
            column(CustomerNo; "Sell-to Customer No.") { }
            column(CustomerPONo; "External Document No.") { }
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
            column(PrepaymentPercent; PrepaymentPercent) { }
            column(PrepaymentAmountDue; PrepaymentAmountDue) { }

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

                RequestedReceiveByDate := GetRequestedReceiveByDate(SalesHeader);
                BuildContactLine();
                FOBText := GetFieldValue(SalesHeader, 'fob');

                CurrencyCode := "Currency Code";
                if CurrencyCode = '' then
                    CurrencyCode := GeneralLedgerSetup."LCY Code";

                TaxAmount := "Amount Including VAT" - Amount;
                PrepaymentPercent := ResolvePrepaymentPercent(
                    "Prepayment %",
                    "Payment Terms Code",
                    PaymentTermsDescription);
                PrepaymentAmountDue := Round("Amount Including VAT" * PrepaymentPercent / 100, 0.01);
            end;
        }
    }

    requestpage
    {
        SaveValues = false;
    }

    rendering
    {
        layout(GPIPrepaymentNotice)
        {
            Type = RDLC;
            Caption = 'GPI Prepayment Notice';
            Summary = 'Gamer-owned Prepayment Notice layout.';
            LayoutFile = 'src/reportlayout/GPIPrepaymentNotice.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
        GeneralLedgerSetup.Get();
    end;

    local procedure GetRequestedReceiveByDate(SalesHeader: Record "Sales Header"): Date
    var
        SalesHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateName: Text;
        CandidateCaption: Text;
        CandidateText: Text;
        ResolvedDate: Date;
    begin
        SalesHeaderRef.GetTable(SalesHeader);
        for FieldIndex := 1 to SalesHeaderRef.FieldCount do begin
            CandidateField := SalesHeaderRef.FieldIndex(FieldIndex);
            CandidateName := LowerCase(CandidateField.Name);
            CandidateCaption := LowerCase(CandidateField.Caption);
            if IsRequestedReceiveDateField(CandidateName, CandidateCaption) then begin
                CandidateText := Format(CandidateField.Value);
                if Evaluate(ResolvedDate, CandidateText) then
                    exit(ResolvedDate);
            end;
        end;
        exit(SalesHeader."Requested Delivery Date");
    end;

    local procedure IsRequestedReceiveDateField(FieldNameText: Text; FieldCaptionText: Text): Boolean
    begin
        exit(
            (StrPos(FieldNameText, 'requested receive by date') > 0) or
            (StrPos(FieldCaptionText, 'requested receive by date') > 0) or
            (StrPos(FieldNameText, 'requested receive date') > 0) or
            (StrPos(FieldCaptionText, 'requested receive date') > 0) or
            (StrPos(FieldNameText, 'receive by date') > 0) or
            (StrPos(FieldCaptionText, 'receive by date') > 0));
    end;

    local procedure BuildContactLine()
    begin
        Clear(ContactLine);
        if (InsideSalespersonName <> '') and (BackupInsideSalespersonName <> '') then
            ContactLine := StrSubstNo('Please contact %1 or %2 at %3 with any questions.', InsideSalespersonName, BackupInsideSalespersonName, CompanyInfo."Phone No.")
        else
            if InsideSalespersonName <> '' then
                ContactLine := StrSubstNo('Please contact %1 at %2 with any questions.', InsideSalespersonName, CompanyInfo."Phone No.")
            else
                ContactLine := StrSubstNo('Please contact Gamer Packaging at %1 with any questions.', CompanyInfo."Phone No.");
    end;

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

    local procedure ResolvePrepaymentPercent(SalesHeaderPrepaymentPercent: Decimal; PaymentTermsCode: Code[10]; PaymentTermsDescriptionText: Text): Decimal
    var
        ParsedPercent: Decimal;
        PaymentTermsText: Text;
    begin
        if SalesHeaderPrepaymentPercent > 0 then
            exit(SalesHeaderPrepaymentPercent);

        PaymentTermsText := PaymentTermsCode + ' ' + PaymentTermsDescriptionText;
        if TryExtractPercentage(PaymentTermsText, ParsedPercent) then
            exit(ParsedPercent);

        if IsAdvancePaymentTerms(PaymentTermsCode, PaymentTermsDescriptionText) then
            exit(100);

        exit(0);
    end;

    local procedure TryExtractPercentage(SourceText: Text; var ParsedPercent: Decimal): Boolean
    var
        PercentPosition: Integer;
        StartPosition: Integer;
        NumberText: Text;
    begin
        PercentPosition := StrPos(SourceText, '%');
        if PercentPosition = 0 then
            exit(false);

        StartPosition := PercentPosition - 1;
        while (StartPosition > 0) and IsPercentageNumberCharacter(CopyStr(SourceText, StartPosition, 1)) do
            StartPosition -= 1;

        NumberText := CopyStr(SourceText, StartPosition + 1, PercentPosition - StartPosition - 1);
        NumberText := DelChr(NumberText, '<>', ' ');
        if NumberText = '' then
            exit(false);

        if not Evaluate(ParsedPercent, NumberText) then
            exit(false);

        exit((ParsedPercent > 0) and (ParsedPercent <= 100));
    end;

    local procedure IsPercentageNumberCharacter(Character: Text[1]): Boolean
    begin
        exit((StrPos('0123456789.,', Character) > 0) or (Character = ' '));
    end;

    local procedure IsAdvancePaymentTerms(PaymentTermsCode: Code[10]; PaymentTermsDescriptionText: Text): Boolean
    var
        SearchValue: Text;
    begin
        SearchValue := LowerCase(PaymentTermsCode + ' ' + PaymentTermsDescriptionText);
        exit(
            (StrPos(SearchValue, 'advance') > 0) or
            (StrPos(SearchValue, 'prepay') > 0) or
            (StrPos(SearchValue, 'pre-pay') > 0));
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
        RequestedReceiveByDate: Date;
        PrepaymentPercent: Decimal;
        PrepaymentAmountDue: Decimal;
}
