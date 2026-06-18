report 70523 "GPI Sales Invoice"
{
    Caption = 'GPI Sales Invoice';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPIInvoice;

    dataset
    {
        dataitem(SalesInvoiceHeader; "Sales Invoice Header")
        {
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
            column(BillToAddress; "Bill-to Address") { }
            column(BillToAddress2; "Bill-to Address 2") { }
            column(BillToCity; "Bill-to City") { }
            column(BillToState; "Bill-to County") { }
            column(BillToPostCode; "Bill-to Post Code") { }
            column(BillToCountry; "Bill-to Country/Region Code") { }

            column(ShipToName; "Ship-to Name") { }
            column(ShipToAddress; "Ship-to Address") { }
            column(ShipToAddress2; "Ship-to Address 2") { }
            column(ShipToCity; "Ship-to City") { }
            column(ShipToState; "Ship-to County") { }
            column(ShipToPostCode; "Ship-to Post Code") { }
            column(ShipToCountry; "Ship-to Country/Region Code") { }

            column(InvoiceTo; "Sell-to Contact") { }
            column(InvoiceNo; "No.") { }
            column(PostingDate; "Posting Date") { }
            column(DocumentDate; "Document Date") { }
            column(DueDate; "Due Date") { }
            column(OrderNo; "Order No.") { }
            column(CustomerNo; "Bill-to Customer No.") { }
            column(CustomerPONo; "External Document No.") { }
            column(LocationCode; "Location Code") { }
            column(ShipmentMethodDescription; ShipmentMethodDescription) { }
            column(PaymentTermsDescription; PaymentTermsDescription) { }
            column(SalespersonName; SalespersonName) { }
            column(ContactLine; ContactLine) { }
            column(CurrencyCode; CurrencyCode) { }
            column(SubtotalAmount; Amount) { }
            column(TaxAmount; TaxAmount) { }
            column(InvoiceTotalAmount; "Amount Including VAT") { }

            dataitem(SalesInvoiceLine; "Sales Invoice Line")
            {
                DataItemLink = "Document No." = field("No.");
                DataItemTableView = sorting("Document No.", "Line No.");

                column(LineNo; "Line No.") { }
                column(ItemNo; "No.") { }
                column(LineDescription; Description) { }
                column(LineDescription2; "Description 2") { }
                column(LineLocationCode; "Location Code") { }
                column(UnitOfMeasureCode; "Unit of Measure Code") { }
                column(Quantity; Quantity) { }
                column(UnitPrice; "Unit Price") { }
                column(LineDiscountPercent; "Line Discount %") { }
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
        layout(GPIInvoice)
        {
            Type = RDLC;
            Caption = 'GPI Sales Invoice';
            Summary = 'Gamer-owned branded posted sales invoice layout.';
            LayoutFile = 'src/reportlayout/GPISalesInvoiceBranded.rdl';
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
        if SalespersonName <> '' then
            ContactLine := StrSubstNo(
                'Please contact %1 at %2 with any questions regarding this invoice.',
                SalespersonName,
                CompanyInfo."Phone No.")
        else
            ContactLine := StrSubstNo(
                'Please contact Gamer Packaging at %1 with any questions regarding this invoice.',
                CompanyInfo."Phone No.");
    end;

    var
        CompanyInfo: Record "Company Information";
        GeneralLedgerSetup: Record "General Ledger Setup";
        ShipmentMethodDescription: Text[100];
        PaymentTermsDescription: Text[100];
        SalespersonName: Text[100];
        ContactLine: Text[250];
        CurrencyCode: Code[10];
        TaxAmount: Decimal;
}
