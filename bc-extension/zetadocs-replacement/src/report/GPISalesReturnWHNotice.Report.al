report 70552 "GPI Sales Return WH Notice"
{
    Caption = 'GPI Sales Return Warehouse Notification';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPISalesReturnWarehouseNotice;

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
            column(ReturnOrderNo; "No.") { }
            column(CustomerNo; "Sell-to Customer No.") { }
            column(CustomerName; "Sell-to Customer Name") { }
            column(CustomerAddressLine; CustomerAddressLine) { }
            column(ContactName; "Sell-to Contact") { }
            column(LocationCode; "Location Code") { }
            column(ExpectedReturnDate; ExpectedReturnDate) { }
            column(CustomerReference; "External Document No.") { }

            dataitem(SalesLine; "Sales Line")
            {
                DataItemLink = "Document Type" = field("Document Type"), "Document No." = field("No.");
                DataItemTableView = sorting("Document Type", "Document No.", "Line No.");

                column(LineNo; "Line No.") { }
                column(ItemNo; "No.") { }
                column(LineDescription; Description) { }
                column(LineDescription2; "Description 2") { }
                column(LineLocationCode; "Location Code") { }
                column(Quantity; DisplayQuantity) { }
                column(UnitOfMeasureCode; DisplayUnitOfMeasureCode) { }
                column(ReturnReasonCode; "Return Reason Code") { }

                trigger OnAfterGetRecord()
                begin
                    if not LineVisibilityMgt.ShouldPrintSalesLine(SalesLine, true) then
                        CurrReport.Skip();

                    DocumentPolicy.GetSalesLineWarehouseDisplay(
                        SalesLine,
                        DisplayQuantity,
                        DisplayUnitOfMeasureCode);
                end;
            }

            trigger OnAfterGetRecord()
            begin
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

                ExpectedReturnDate := "Requested Delivery Date";
                if ExpectedReturnDate = 0D then
                    ExpectedReturnDate := "Shipment Date";
            end;
        }
    }

    requestpage
    {
        SaveValues = false;
    }

    rendering
    {
        layout(GPISalesReturnWarehouseNotice)
        {
            Type = RDLC;
            Caption = 'GPI Sales Return Warehouse Notification';
            Summary = 'Warehouse-facing Gamer Sales Return Notification.';
            LayoutFile = 'src/reportlayout/GPISalesReturnWarehouseNotificationBranded.rdl';
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

    var
        CompanyInfo: Record "Company Information";
        LineVisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        DocumentPolicy: Codeunit "GPI Document Policy Mgt.";
        CompanyAddressLine: Text[250];
        CustomerAddressLine: Text[250];
        ExpectedReturnDate: Date;
        DisplayQuantity: Decimal;
        DisplayUnitOfMeasureCode: Code[10];
}
