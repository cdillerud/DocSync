report 70551 "GPI Sales Return Auth."
{
    Caption = 'GPI Sales Return Authorization';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPISalesReturnAuthorization;

    dataset
    {
        dataitem(SalesHeader; "Sales Header")
        {
            DataItemTableView = sorting("Document Type", "No.") where("Document Type" = const("Return Order"));
            RequestFilterFields = "No.";

            column(CompanyLogo; CompanyInfo.Picture) { }
            column(CompanyName; CompanyInfo.Name) { }
            column(CompanyAddressLine; CompanyAddressLine) { }
            column(CompanyPhone; CompanyInfo."Phone No.") { }
            column(CustomerName; "Sell-to Customer Name") { }
            column(CustomerAddressLine; CustomerAddressLine) { }
            column(ContactName; "Sell-to Contact") { }
            column(ReturnOrderNo; "No.") { }
            column(AuthorizationDate; "Order Date") { }
            column(ExpectedReturnDate; ExpectedReturnDate) { }
            column(CustomerNo; "Sell-to Customer No.") { }
            column(CustomerReference; "External Document No.") { }
            column(LocationCode; "Location Code") { }
            column(SalespersonName; SalespersonName) { }
            column(InsideSalespersonName; InsideSalespersonName) { }
            column(ContactLine; ContactLine) { }

            dataitem(SalesLine; "Sales Line")
            {
                DataItemLink = "Document Type" = field("Document Type"), "Document No." = field("No.");
                DataItemTableView = sorting("Document Type", "Document No.", "Line No.");

                column(LineNo; "Line No.") { }
                column(ItemNo; "No.") { }
                column(LineDescription; Description) { }
                column(LineDescription2; "Description 2") { }
                column(Quantity; Quantity) { }
                column(UnitOfMeasureCode; "Unit of Measure Code") { }
                column(ReturnReasonCode; "Return Reason Code") { }

                trigger OnAfterGetRecord()
                begin
                    if not LineVisibilityMgt.ShouldPrintSalesLine(SalesLine, false) then
                        CurrReport.Skip();
                end;
            }

            trigger OnAfterGetRecord()
            var
                Salesperson: Record "Salesperson/Purchaser";
                InsideSalespersonCode: Code[20];
            begin
                LineVisibilityMgt.ValidateSalesExternalDocument(SalesHeader);

                CompanyAddressLine := BuildAddressLine(
                    CompanyInfo.Address,
                    CompanyInfo."Address 2",
                    CompanyInfo.City,
                    CompanyInfo.County,
                    CompanyInfo."Post Code");
                CustomerAddressLine := BuildAddressLine(
                    "Sell-to Address",
                    "Sell-to Address 2",
                    "Sell-to City",
                    "Sell-to County",
                    "Sell-to Post Code");

                Clear(SalespersonName);
                if Salesperson.Get("Salesperson Code") then
                    SalespersonName := Salesperson.Name;

                InsideSalespersonCode := GetInsideSalespersonCode(SalesHeader);
                Clear(InsideSalespersonName);
                if (InsideSalespersonCode <> '') and Salesperson.Get(InsideSalespersonCode) then
                    InsideSalespersonName := Salesperson.Name;

                ExpectedReturnDate := "Requested Delivery Date";
                if ExpectedReturnDate = 0D then
                    ExpectedReturnDate := "Shipment Date";

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
        layout(GPISalesReturnAuthorization)
        {
            Type = RDLC;
            Caption = 'GPI Sales Return Authorization';
            Summary = 'Customer-facing Gamer Sales Return Authorization.';
            LayoutFile = 'src/reportlayout/GPISalesReturnAuthorizationBranded.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
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
                'Please contact %1 at %2 with questions about this return authorization.',
                InsideSalespersonName,
                CompanyInfo."Phone No.")
        else
            ContactLine := StrSubstNo(
                'Please contact Gamer Packaging at %1 with questions about this return authorization.',
                CompanyInfo."Phone No.");
    end;

    local procedure GetInsideSalespersonCode(SalesHeader: Record "Sales Header"): Code[20]
    var
        SalesHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        FieldIdentity: Text;
        CandidateValue: Text;
    begin
        SalesHeaderRef.GetTable(SalesHeader);
        for FieldIndex := 1 to SalesHeaderRef.FieldCount do begin
            CandidateField := SalesHeaderRef.FieldIndex(FieldIndex);
            FieldIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if ((StrPos(FieldIdentity, 'inside salesperson') > 0) or
                (StrPos(FieldIdentity, 'inside sales') > 0) or
                (StrPos(FieldIdentity, 'isr') > 0)) and
               (StrPos(FieldIdentity, 'backup') = 0)
            then begin
                CandidateValue := Format(CandidateField.Value);
                exit(CopyStr(CandidateValue, 1, 20));
            end;
        end;
        exit('');
    end;

    var
        CompanyInfo: Record "Company Information";
        LineVisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        CompanyAddressLine: Text[250];
        CustomerAddressLine: Text[250];
        SalespersonName: Text[100];
        InsideSalespersonName: Text[100];
        ContactLine: Text[250];
        ExpectedReturnDate: Date;
}
