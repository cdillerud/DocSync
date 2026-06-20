report 70561 "GPI Purchase Return Pick"
{
    Caption = 'GPI Purchase Return Pick Ticket';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPIPurchaseReturnPick;

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
            column(ReturnOrderNo; "No.") { }
            column(VendorNo; "Buy-from Vendor No.") { }
            column(VendorName; "Buy-from Vendor Name") { }
            column(ReturnToAddressLine; ReturnToAddressLine) { }
            column(VendorContact; "Buy-from Contact") { }
            column(LocationCode; "Location Code") { }
            column(PostingDate; "Posting Date") { }
            column(YourReference; "Your Reference") { }

            dataitem(PurchaseLine; "Purchase Line")
            {
                DataItemLink = "Document Type" = field("Document Type"), "Document No." = field("No.");
                DataItemTableView = sorting("Document Type", "Document No.", "Line No.");

                column(ItemNo; "No.") { }
                column(VendorItemNo; "Vendor Item No.") { }
                column(LineDescription; Description) { }
                column(LineDescription2; "Description 2") { }
                column(LineLocationCode; "Location Code") { }
                column(Quantity; DisplayQuantity) { }
                column(UnitOfMeasureCode; DisplayUnitOfMeasureCode) { }
                column(ReturnReasonCode; "Return Reason Code") { }

                trigger OnPreDataItem()
                begin
                    SetFilter("No.", '<>%1', '');
                end;

                trigger OnAfterGetRecord()
                begin
                    if not LineVisibilityMgt.ShouldPrintPurchaseLine(PurchaseLine, true) then
                        CurrReport.Skip();

                    DocumentPolicy.GetPurchaseLineWarehouseDisplay(
                        PurchaseLine,
                        DisplayQuantity,
                        DisplayUnitOfMeasureCode);
                end;
            }

            trigger OnAfterGetRecord()
            begin
                TestField("Location Code");
                CompanyAddressLine := BuildAddressLine(
                    CompanyInfo.Address,
                    CompanyInfo."Address 2",
                    CompanyInfo.City,
                    CompanyInfo.County,
                    CompanyInfo."Post Code");
                ReturnToAddressLine := BuildAddressLine(
                    "Buy-from Address",
                    "Buy-from Address 2",
                    "Buy-from City",
                    "Buy-from County",
                    "Buy-from Post Code");
            end;
        }
    }

    requestpage
    {
        SaveValues = false;
    }

    rendering
    {
        layout(GPIPurchaseReturnPick)
        {
            Type = RDLC;
            Caption = 'GPI Purchase Return Pick Ticket';
            Summary = 'Warehouse-facing Gamer Purchase Return Pick Ticket.';
            LayoutFile = 'src/reportlayout/GPIPurchaseReturnPickTicketBranded.rdl';
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
        ReturnToAddressLine: Text[250];
        DisplayQuantity: Decimal;
        DisplayUnitOfMeasureCode: Code[10];
}
