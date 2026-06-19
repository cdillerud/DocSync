report 70529 "GPI Purchase Credit Memo"
{
    Caption = 'GPI Purchase Credit Memo';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPIPurchaseCreditMemo;

    dataset
    {
        dataitem(PurchaseCreditMemoHeader; "Purch. Cr. Memo Hdr.")
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

            column(BillToName; "Pay-to Name") { }
            column(BillToAddress; "Pay-to Address") { }
            column(BillToCity; "Pay-to City") { }
            column(BillToState; "Pay-to County") { }
            column(BillToPostCode; "Pay-to Post Code") { }

            column(ShipToName; "Buy-from Vendor Name") { }
            column(ShipToAddress; "Buy-from Address") { }
            column(ShipToCity; "Buy-from City") { }
            column(ShipToState; "Buy-from County") { }
            column(ShipToPostCode; "Buy-from Post Code") { }

            column(InvoiceNo; "No.") { }
            column(PostingDate; "Posting Date") { }
            column(DueDate; "Due Date") { }
            column(OrderNo; RelatedDocumentNo) { }
            column(CustomerNo; "Buy-from Vendor No.") { }
            column(CustomerPONo; "Vendor Cr. Memo No.") { }
            column(PaymentTermsDescription; PaymentTermsDescription) { }
            column(CurrencyCode; CurrencyCode) { }
            column(SubtotalAmount; Amount) { }
            column(TaxAmount; TaxAmount) { }
            column(InvoiceTotalAmount; "Amount Including VAT") { }
            column(ContactLine; ContactLine) { }

            dataitem(PurchaseCreditMemoLine; "Purch. Cr. Memo Line")
            {
                DataItemLink = "Document No." = field("No.");
                DataItemTableView = sorting("Document No.", "Line No.");

                column(ItemNo; "No.") { }
                column(LineDescription; Description) { }
                column(LineDescription2; "Description 2") { }
                column(Quantity; Quantity) { }
                column(UnitPrice; "Direct Unit Cost") { }
                column(LineAmount; "Line Amount") { }

                trigger OnPreDataItem()
                begin
                    SetFilter("No.", '<>%1', '');
                end;
            }

            trigger OnAfterGetRecord()
            var
                PaymentTerms: Record "Payment Terms";
                Purchaser: Record "Salesperson/Purchaser";
            begin
                CalcFields(Amount, "Amount Including VAT");

                Clear(PaymentTermsDescription);
                if PaymentTerms.Get("Payment Terms Code") then
                    PaymentTermsDescription := PaymentTerms.Description;

                Clear(PurchaserName);
                if Purchaser.Get("Purchaser Code") then
                    PurchaserName := Purchaser.Name;

                CurrencyCode := "Currency Code";
                if CurrencyCode = '' then
                    CurrencyCode := GeneralLedgerSetup."LCY Code";

                TaxAmount := "Amount Including VAT" - Amount;
                RelatedDocumentNo := GetRelatedDocumentNo(PurchaseCreditMemoHeader);
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
        layout(GPIPurchaseCreditMemo)
        {
            Type = RDLC;
            Caption = 'GPI Purchase Credit Memo';
            Summary = 'Gamer-owned branded posted purchase credit memo layout.';
            LayoutFile = 'src/reportlayout/GPIPurchaseCreditMemoBranded.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
        GeneralLedgerSetup.Get();
    end;

    local procedure GetRelatedDocumentNo(PurchaseCreditMemoHeader: Record "Purch. Cr. Memo Hdr."): Code[20]
    var
        HeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        FieldIdentity: Text;
        FieldValue: Text;
    begin
        HeaderRef.GetTable(PurchaseCreditMemoHeader);
        for FieldIndex := 1 to HeaderRef.FieldCount do begin
            CandidateField := HeaderRef.FieldIndex(FieldIndex);
            FieldIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if (StrPos(FieldIdentity, 'return shipment no') > 0) or
               (StrPos(FieldIdentity, 'applies-to doc. no') > 0) or
               (StrPos(FieldIdentity, 'order no') > 0)
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
        if PurchaserName <> '' then
            ContactLine := StrSubstNo(
                'Please contact %1 at %2 with any questions regarding this purchase credit memo.',
                PurchaserName,
                CompanyInfo."Phone No.")
        else
            ContactLine := StrSubstNo(
                'Please contact Gamer Packaging at %1 with any questions regarding this purchase credit memo.',
                CompanyInfo."Phone No.");
    end;

    var
        CompanyInfo: Record "Company Information";
        GeneralLedgerSetup: Record "General Ledger Setup";
        PaymentTermsDescription: Text[100];
        PurchaserName: Text[100];
        ContactLine: Text[250];
        CurrencyCode: Code[10];
        RelatedDocumentNo: Code[20];
        TaxAmount: Decimal;
}
