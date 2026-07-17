report 70527 "GPI Warehouse Receiving Notice"
{
    Caption = 'GPI Warehouse Receiving Notice';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPIWarehouseReceiving;

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

            column(PurchaseOrderNo; "No.") { }
            column(OrderDate; "Order Date") { }
            column(ExpectedReceiptDate; "Expected Receipt Date") { }
            column(WarehouseReceiptDate; "GPI WH Receipt Date") { }
            column(LocationCode; "Location Code") { }
            column(LocationName; LocationName) { }
            column(LocationAddress; LocationAddress) { }
            column(LocationCityStateZip; LocationCityStateZip) { }
            column(LocationContact; LocationContact) { }
            column(VendorNo; "Buy-from Vendor No.") { }
            column(VendorName; "Buy-from Vendor Name") { }
            column(VendorContact; "Buy-from Contact") { }
            column(ShipmentMethodDescription; ShipmentMethodDescription) { }
            column(PurchaserName; PurchaserName) { }
            column(GamerContactName1; GamerContactName1) { }
            column(GamerContactName2; GamerContactName2) { }
            column(ContactLine; ContactLine) { }

            dataitem(PurchaseLine; "Purchase Line")
            {
                DataItemLink = "Document Type" = field("Document Type"), "Document No." = field("No.");
                DataItemTableView = sorting("Document Type", "Document No.", "Line No.");

                column(ItemNo; "No.") { }
                column(LineDescription; Description) { }
                column(Quantity; WarehouseQuantity) { }
                column(UnitOfMeasureCode; WarehouseUnitOfMeasureCode) { }
                column(LineExpectedReceiptDate; "Expected Receipt Date") { }

                trigger OnPreDataItem()
                begin
                    SetFilter("No.", '<>%1', '');
                end;

                trigger OnAfterGetRecord()
                begin
                    DocumentPolicy.GetPurchaseLineWarehouseDisplay(
                        PurchaseLine,
                        WarehouseQuantity,
                        WarehouseUnitOfMeasureCode);
                end;
            }

            trigger OnAfterGetRecord()
            var
                Location: Record Location;
                ShipmentMethod: Record "Shipment Method";
                Purchaser: Record "Salesperson/Purchaser";
            begin
                TestField("Location Code");
                TestField("GPI WH Receipt Date");

                Clear(LocationName);
                Clear(LocationAddress);
                Clear(LocationCityStateZip);
                Clear(LocationContact);
                if Location.Get("Location Code") then begin
                    LocationName := Location.Name;
                    LocationAddress := Location.Address;
                    LocationCityStateZip := StrSubstNo('%1, %2 %3', Location.City, Location.County, Location."Post Code");
                    LocationContact := Location.Contact;
                end;

                GPIBuildGamerContactNames(PurchaseHeader);


                Clear(ShipmentMethodDescription);
                if ShipmentMethod.Get("Shipment Method Code") then
                    ShipmentMethodDescription := ShipmentMethod.Description;

                Clear(PurchaserName);
                if ("Purchaser Code" <> '') and Purchaser.Get("Purchaser Code") then
                    PurchaserName := Purchaser.Name;

                if PurchaserName <> '' then
                    ContactLine := StrSubstNo('Questions? Contact %1 at %2.', PurchaserName, CompanyInfo."Phone No.")
                else
                    ContactLine := StrSubstNo('Questions? Contact Gamer Packaging at %1.', CompanyInfo."Phone No.");
            end;
        }
    }

    requestpage
    {
        SaveValues = false;
    }

    rendering
    {
        layout(GPIWarehouseReceiving)
        {
            Type = RDLC;
            Caption = 'GPI Warehouse Receiving Notice';
            Summary = 'Gamer-owned warehouse receiving notice.';
            LayoutFile = 'src/reportlayout/GPIWarehouseReceivingNoticeBranded.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
    end;

    local procedure GPIBuildGamerContactNames(PurchaseHeader: Record "Purchase Header")
    var
        Salesperson: Record "Salesperson/Purchaser";
        SalespersonCode: Code[20];
    begin
        Clear(GamerContactName1);
        Clear(GamerContactName2);

        if (PurchaseHeader."Purchaser Code" <> '') and Salesperson.Get(PurchaseHeader."Purchaser Code") then
            GPIAddGamerContactName(Salesperson.Name);

        SalespersonCode := GPIFindSalespersonCode(PurchaseHeader, false);
        if (SalespersonCode <> '') and Salesperson.Get(SalespersonCode) then
            GPIAddGamerContactName(Salesperson.Name);

        SalespersonCode := GPIFindSalespersonCode(PurchaseHeader, true);
        if (SalespersonCode <> '') and Salesperson.Get(SalespersonCode) then
            GPIAddGamerContactName(Salesperson.Name);
    end;

    local procedure GPIAddGamerContactName(ContactName: Text[100])
    begin
        ContactName := CopyStr(DelChr(ContactName, '<>', ' '), 1, MaxStrLen(ContactName));
        if ContactName = '' then
            exit;

        if (GamerContactName1 = ContactName) or (GamerContactName2 = ContactName) then
            exit;

        if GamerContactName1 = '' then begin
            GamerContactName1 := ContactName;
            exit;
        end;

        if GamerContactName2 = '' then
            GamerContactName2 := ContactName;
    end;

    local procedure GPIFindSalespersonCode(PurchaseHeader: Record "Purchase Header"; InsideSales: Boolean): Code[20]
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
    var
        CompanyInfo: Record "Company Information";
        DocumentPolicy: Codeunit "GPI Document Policy Mgt.";
        LocationName: Text[100];
        LocationAddress: Text[100];
        LocationCityStateZip: Text[150];
        LocationContact: Text[100];
        ShipmentMethodDescription: Text[100];
        PurchaserName: Text[100];
        GamerContactName1: Text[100];
        GamerContactName2: Text[100];
        ContactLine: Text[250];
        WarehouseQuantity: Decimal;
        WarehouseUnitOfMeasureCode: Code[10];
}