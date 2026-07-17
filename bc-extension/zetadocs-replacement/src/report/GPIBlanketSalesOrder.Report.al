report 70524 "GPI Blanket Sales Order"
{
    Caption = 'GPI Blanket Sales Order';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPIBlanketOrder;

    dataset
    {
        dataitem(SalesHeader; "Sales Header")
        {
            DataItemTableView = sorting("Document Type", "No.") where("Document Type" = const("Blanket Order"));
            RequestFilterFields = "No.";

            column(CompanyLogo; CompanyInfo.Picture) { }
            column(CompanyName; CompanyInfo.Name) { }
            column(CompanyAddress; CompanyInfo.Address) { }
            column(CompanyCity; CompanyInfo.City) { }
            column(CompanyState; CompanyInfo.County) { }
            column(CompanyPostCode; CompanyInfo."Post Code") { }
            column(CompanyPhone; CompanyInfo."Phone No.") { }
            column(CompanyHomePage; CompanyInfo."Home Page") { }
            column(BillToName; "Bill-to Name") { }
            column(BillToAddress; "Bill-to Address") { }
            column(BillToCity; "Bill-to City") { }
            column(BillToState; "Bill-to County") { }
            column(BillToPostCode; "Bill-to Post Code") { }
            column(ShipToName; "Ship-to Name") { }
            column(ShipToAddress; "Ship-to Address") { }
            column(ShipToCity; "Ship-to City") { }
            column(ShipToState; "Ship-to County") { }
            column(ShipToPostCode; "Ship-to Post Code") { }
            column(BlanketOrderNo; "No.") { }
            column(OrderDate; "Order Date") { }
            column(RequestedDeliveryDate; "Requested Delivery Date") { }
            column(CustomerNo; "Sell-to Customer No.") { }
            column(CustomerPONo; "External Document No.") { }
            column(ContactName; "Sell-to Contact") { }
            column(LocationCode; "Location Code") { }
            column(PaymentTermsDescription; PaymentTermsDescription) { }
            column(ShipmentMethodDescription; ShipmentMethodDescription) { }
            column(SalespersonName; SalespersonName) { }
            column(InsideSalespersonName; InsideSalespersonName) { }
            column(BackupInsideSalespersonName; BackupInsideSalespersonName) { }
            column(ContactLine; ContactLine) { }
            column(CurrencyCode; CurrencyCode) { }
            column(SubtotalAmount; Amount) { }
            column(TaxAmount; TaxAmount) { }
            column(TotalAmount; "Amount Including VAT") { }

            dataitem(SalesLine; "Sales Line")
            {
                DataItemLink = "Document Type" = field("Document Type"), "Document No." = field("No.");
                DataItemTableView = sorting("Document Type", "Document No.", "Line No.");

                column(ItemNo; "No.") { }
                column(LineDescription; Description) { }
                column(Quantity; Quantity) { }
                column(UnitOfMeasureCode; "Unit of Measure Code") { }
                column(UnitPrice; "Unit Price") { }
                column(LineAmount; "Line Amount") { }

                trigger OnPreDataItem()
                begin
                    SetFilter("No.", '<>%1', '');
                end;
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
                CurrencyCode := "Currency Code";
                if CurrencyCode = '' then
                    CurrencyCode := GeneralLedgerSetup."LCY Code";
                TaxAmount := "Amount Including VAT" - Amount;
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
        layout(GPIBlanketOrder)
        {
            Type = RDLC;
            Caption = 'GPI Blanket Sales Order';
            Summary = 'Gamer-owned branded blanket sales order layout.';
            LayoutFile = 'src/reportlayout/GPIBlanketSalesOrderBranded.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
        GeneralLedgerSetup.Get();
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
    local procedure BuildContactLine()
    begin
        if SalespersonName <> '' then
            ContactLine := StrSubstNo('Please contact %1 at %2 with any questions regarding this blanket sales order.', SalespersonName, CompanyInfo."Phone No.")
        else
            ContactLine := StrSubstNo('Please contact Gamer Packaging at %1 with any questions regarding this blanket sales order.', CompanyInfo."Phone No.");
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
        CurrencyCode: Code[10];
        TaxAmount: Decimal;
}
