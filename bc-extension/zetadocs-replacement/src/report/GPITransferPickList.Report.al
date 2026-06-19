report 70570 "GPI Transfer Pick List"
{
    Caption = 'GPI Transfer Pick List';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPITransferPickList;

    dataset
    {
        dataitem(TransferHeader; "Transfer Header")
        {
            RequestFilterFields = "No.";

            column(CompanyLogo; CompanyInfo.Picture) { }
            column(CompanyName; CompanyInfo.Name) { }
            column(CompanyAddressLine; CompanyAddressLine) { }
            column(CompanyPhone; CompanyInfo."Phone No.") { }
            column(TransferOrderNo; "No.") { }
            column(TransferFromCode; "Transfer-from Code") { }
            column(TransferToCode; "Transfer-to Code") { }
            column(ShipmentDate; "Shipment Date") { }
            column(ReceiptDate; "Receipt Date") { }
            column(InTransitCode; "In-Transit Code") { }
            column(ExternalDocumentNo; "External Document No.") { }
            column(FromLocationName; FromLocationName) { }
            column(FromLocationAddress; FromLocationAddress) { }
            column(ToLocationName; ToLocationName) { }
            column(ToLocationAddress; ToLocationAddress) { }

            dataitem(TransferLine; "Transfer Line")
            {
                DataItemLink = "Document No." = field("No.");
                DataItemTableView = sorting("Document No.", "Line No.");

                column(ItemNo; "Item No.") { }
                column(LineDescription; Description) { }
                column(Quantity; Quantity) { }
                column(UnitOfMeasureCode; "Unit of Measure Code") { }
                column(LineShipmentDate; "Shipment Date") { }
                column(LineReceiptDate; "Receipt Date") { }

                trigger OnAfterGetRecord()
                begin
                    if not TransferVisibilityMgt.ShouldPrintOnPickList(TransferLine) then
                        CurrReport.Skip();
                end;
            }

            trigger OnAfterGetRecord()
            begin
                ResolveLocationDetails(
                    "Transfer-from Code",
                    FromLocationName,
                    FromLocationAddress);
                ResolveLocationDetails(
                    "Transfer-to Code",
                    ToLocationName,
                    ToLocationAddress);
            end;
        }
    }

    requestpage
    {
        SaveValues = false;
    }

    rendering
    {
        layout(GPITransferPickList)
        {
            Type = RDLC;
            Caption = 'GPI Transfer Pick List';
            Summary = 'Warehouse-facing Gamer Transfer Pick List.';
            LayoutFile = 'src/reportlayout/GPITransferPickListBranded.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
        CompanyAddressLine := BuildAddressLine(
            CompanyInfo.Address,
            CompanyInfo."Address 2",
            CompanyInfo.City,
            CompanyInfo.County,
            CompanyInfo."Post Code");
    end;

    local procedure ResolveLocationDetails(LocationCode: Code[10]; var LocationName: Text[100]; var LocationAddress: Text[250])
    var
        Location: Record Location;
    begin
        Clear(LocationName);
        Clear(LocationAddress);
        if not Location.Get(LocationCode) then
            exit;

        LocationName := Location.Name;
        LocationAddress := BuildAddressLine(
            Location.Address,
            Location."Address 2",
            Location.City,
            Location.County,
            Location."Post Code");
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
        TransferVisibilityMgt: Codeunit "GPI Transfer Visibility Mgt.";
        CompanyAddressLine: Text[250];
        FromLocationName: Text[100];
        FromLocationAddress: Text[250];
        ToLocationName: Text[100];
        ToLocationAddress: Text[250];
}
