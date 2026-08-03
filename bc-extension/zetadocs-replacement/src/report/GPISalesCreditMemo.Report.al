report 70528 "GPI Sales Credit Memo"
{
    Caption = 'GPI Sales Credit Memo';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPICreditMemo;

    dataset
    {
        dataitem(SalesCreditMemoHeader; "Sales Cr.Memo Header")
        {
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

            column(InvoiceNo; "No.") { }
            column(PostingDate; "Posting Date") { }
            column(DueDate; "Due Date") { }
            column(OrderNo; RelatedDocumentNo) { }
            column(CustomerNo; "Bill-to Customer No.") { }
            column(CustomerPONo; "External Document No.") { }
            column(PaymentTermsDescription; PaymentTermsDescription) { }
            column(CurrencyCode; CurrencyCode) { }
            column(SubtotalAmount; Amount) { }
            column(TaxAmount; TaxAmount) { }
            column(InvoiceTotalAmount; "Amount Including VAT") { }
            column(ContactLine; ContactLine) { }

            dataitem(SalesCreditMemoLine; "Sales Cr.Memo Line")
            {
                DataItemLink = "Document No." = field("No.");
                DataItemTableView = sorting("Document No.", "Line No.");

                column(ItemNo; "No.") { }
                column(LineDescription; Description) { }
                column(LineDescription2; "Description 2") { }
                column(Quantity; Quantity) { }
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
                Salesperson: Record "Salesperson/Purchaser";
            begin
                CalcFields(Amount, "Amount Including VAT");

                Clear(PaymentTermsDescription);
                if PaymentTerms.Get("Payment Terms Code") then
                    PaymentTermsDescription := PaymentTerms.Description;

                Clear(SalespersonName);
                if Salesperson.Get("Salesperson Code") then
                    SalespersonName := Salesperson.Name;

                CurrencyCode := "Currency Code";
                if CurrencyCode = '' then
                    CurrencyCode := GeneralLedgerSetup."LCY Code";

                TaxAmount := "Amount Including VAT" - Amount;
                RelatedDocumentNo := GetRelatedDocumentNo(SalesCreditMemoHeader);
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
        layout(GPICreditMemo)
        {
            Type = RDLC;
            Caption = 'GPI Sales Credit Memo';
            Summary = 'Gamer-owned branded posted sales credit memo layout.';
            LayoutFile = 'src/reportlayout/GPISalesCreditMemoBranded.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
        GeneralLedgerSetup.Get();
    end;

    local procedure GetRelatedDocumentNo(SalesCreditMemoHeader: Record "Sales Cr.Memo Header"): Code[20]
    var
        HeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        FieldIdentity: Text;
        FieldValue: Text;
    begin
        HeaderRef.GetTable(SalesCreditMemoHeader);
        for FieldIndex := 1 to HeaderRef.FieldCount do begin
            CandidateField := HeaderRef.FieldIndex(FieldIndex);
            FieldIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if (StrPos(FieldIdentity, 'return order no') > 0) or
               (StrPos(FieldIdentity, 'applies-to doc. no') > 0)
            then begin
                FieldValue := DelChr(Format(CandidateField.Value), '<>', ' ');
                if FieldValue <> '' then
                    exit(CopyStr(FieldValue, 1, 20));
            end;
        end;

        exit('');
    end;

    local procedure BuildContactLine()
    begin
        if SalespersonName <> '' then
            ContactLine := StrSubstNo(
                'Please contact %1 at %2 with any questions regarding this credit memo.',
                SalespersonName,
                CompanyInfo."Phone No.")
        else
            ContactLine := StrSubstNo(
                'Please contact Gamer Packaging at %1 with any questions regarding this credit memo.',
                CompanyInfo."Phone No.");
    end;

    var
        CompanyInfo: Record "Company Information";
        GeneralLedgerSetup: Record "General Ledger Setup";
        PaymentTermsDescription: Text[100];
        SalespersonName: Text[100];
        ContactLine: Text[250];
        CurrencyCode: Code[10];
        RelatedDocumentNo: Code[20];
        TaxAmount: Decimal;
}
