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
            column(ContactLine; ContactLine) { }

            dataitem(PurchaseLine; "Purchase Line")
            {
                DataItemLink = "Document Type" = field("Document Type"), "Document No." = field("No.");
                DataItemTableView = sorting("Document Type", "Document No.", "Line No.");

                column(ItemNo; "No.") { }
                column(LineDescription; Description) { }
                column(Quantity; Quantity) { }
                column(UnitOfMeasureCode; "Unit of Measure Code") { }
                column(LineExpectedReceiptDate; "Expected Receipt Date") { }

                trigger OnPreDataItem()
                begin
                    SetFilter("No.", '<>%1', '');
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

    var
        CompanyInfo: Record "Company Information";
        LocationName: Text[100];
        LocationAddress: Text[100];
        LocationCityStateZip: Text[150];
        LocationContact: Text[100];
        ShipmentMethodDescription: Text[100];
        PurchaserName: Text[100];
        ContactLine: Text[250];
}
