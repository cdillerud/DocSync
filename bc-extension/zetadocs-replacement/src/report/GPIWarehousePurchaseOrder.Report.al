report 70526 "GPI Warehouse Purchase Order"
{
    Caption = 'GPI Warehouse Purchase Order';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPIWarehousePO;

    dataset
    {
        dataitem(PurchaseHeader; "Purchase Header")
        {
            DataItemTableView = sorting("Document Type", "No.") where("Document Type" = const(Order));
            RequestFilterFields = "No.";

            column(CompanyLogo; CompanyInfo.Picture) { }
            column(CompanyName; CompanyInfo.Name) { }
            column(CompanyAddress; CompanyInfo.Address) { }
            column(CompanyCity; CompanyInfo.City) { }
            column(CompanyState; CompanyInfo.County) { }
            column(CompanyPostCode; CompanyInfo."Post Code") { }
            column(CompanyPhone; CompanyInfo."Phone No.") { }
            column(CompanyHomePage; CompanyInfo."Home Page") { }

            column(VendorName; "Buy-from Vendor Name") { }
            column(VendorAddress; "Buy-from Address") { }
            column(VendorCity; "Buy-from City") { }
            column(VendorState; "Buy-from County") { }
            column(VendorPostCode; "Buy-from Post Code") { }
            column(VendorContact; "Buy-from Contact") { }

            column(ShipToName; "Ship-to Name") { }
            column(ShipToAddress; "Ship-to Address") { }
            column(ShipToCity; "Ship-to City") { }
            column(ShipToState; "Ship-to County") { }
            column(ShipToPostCode; "Ship-to Post Code") { }
            column(ShipToContact; "Ship-to Contact") { }

            column(PurchaseOrderNo; "No.") { }
            column(OrderDate; "Order Date") { }
            column(ExpectedReceiptDate; "Expected Receipt Date") { }
            column(VendorNo; "Buy-from Vendor No.") { }
            column(CustomerNo; "Sell-to Customer No.") { }
            column(YourReference; "Your Reference") { }
            column(LocationCode; "Location Code") { }
            column(PaymentTermsDescription; PaymentTermsDescription) { }
            column(ShipmentMethodDescription; ShipmentMethodDescription) { }
            column(PurchaserName; PurchaserName) { }
            column(ContactLine; ContactLine) { }
            column(CurrencyCode; CurrencyCode) { }
            column(SubtotalAmount; Amount) { }
            column(TaxAmount; TaxAmount) { }
            column(TotalAmount; "Amount Including VAT") { }

            dataitem(PurchaseLine; "Purchase Line")
            {
                DataItemLink = "Document Type" = field("Document Type"), "Document No." = field("No.");
                DataItemTableView = sorting("Document Type", "Document No.", "Line No.");

                column(ItemNo; "No.") { }
                column(LineDescription; Description) { }
                column(Quantity; Quantity) { }
                column(UnitOfMeasureCode; "Unit of Measure Code") { }
                column(DirectUnitCost; "Direct Unit Cost") { }
                column(LineAmount; "Line Amount") { }
                column(LineExpectedReceiptDate; "Expected Receipt Date") { }
                column(VendorItemNo; "Vendor Item No.") { }

                trigger OnPreDataItem()
                begin
                    SetFilter("No.", '<>%1', '');
                end;
            }

            trigger OnAfterGetRecord()
            var
                PaymentTerms: Record "Payment Terms";
                ShipmentMethod: Record "Shipment Method";
            begin
                TestField("Location Code");
                if "Location Code" = '00' then
                    Error('Purchase Order %1 is a drop-ship order. Use the Drop Ship Purchase Order document instead.', "No.");

                CalcFields(Amount, "Amount Including VAT");

                Clear(PaymentTermsDescription);
                if PaymentTerms.Get("Payment Terms Code") then
                    PaymentTermsDescription := PaymentTerms.Description;

                Clear(ShipmentMethodDescription);
                if ShipmentMethod.Get("Shipment Method Code") then
                    ShipmentMethodDescription := ShipmentMethod.Description;

                ResolvePurchaserName(PurchaseHeader);

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
        layout(GPIWarehousePO)
        {
            Type = RDLC;
            Caption = 'GPI Warehouse Purchase Order';
            Summary = 'Gamer-owned branded warehouse purchase order layout.';
            LayoutFile = 'src/reportlayout/GPIWarehousePurchaseOrderBranded.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
        GeneralLedgerSetup.Get();
    end;

    local procedure ResolvePurchaserName(PurchaseHeader: Record "Purchase Header")
    var
        Salesperson: Record "Salesperson/Purchaser";
        SalespersonCode: Code[20];
    begin
        Clear(PurchaserName);

        if (PurchaseHeader."Purchaser Code" <> '') and Salesperson.Get(PurchaseHeader."Purchaser Code") then begin
            PurchaserName := Salesperson.Name;
            exit;
        end;

        SalespersonCode := FindSalespersonCode(PurchaseHeader, false);
        if (SalespersonCode <> '') and Salesperson.Get(SalespersonCode) then begin
            PurchaserName := Salesperson.Name;
            exit;
        end;

        SalespersonCode := FindSalespersonCode(PurchaseHeader, true);
        if (SalespersonCode <> '') and Salesperson.Get(SalespersonCode) then
            PurchaserName := Salesperson.Name;
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

    local procedure BuildContactLine()
    begin
        if PurchaserName <> '' then
            ContactLine := StrSubstNo(
                'Please contact %1 at %2 with any questions regarding this purchase order.',
                PurchaserName,
                CompanyInfo."Phone No.")
        else
            ContactLine := StrSubstNo(
                'Please contact Gamer Packaging at %1 with any questions regarding this purchase order.',
                CompanyInfo."Phone No.");
    end;

    var
        CompanyInfo: Record "Company Information";
        GeneralLedgerSetup: Record "General Ledger Setup";
        PaymentTermsDescription: Text[100];
        ShipmentMethodDescription: Text[100];
        PurchaserName: Text[100];
        ContactLine: Text[250];
        CurrencyCode: Code[10];
        TaxAmount: Decimal;
}
