table 71004 "GPI Pack Cost Work"
{
    Caption = 'GPI Packaging Landed Cost Worksheet';
    DataClassification = CustomerContent;
    LookupPageId = "GPI Pack Cost Works";
    DrillDownPageId = "GPI Pack Cost Works";

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; "Product No."; Code[20])
        {
            Caption = 'Gamer ID';
            TableRelation = "GPI Pack Product"."No.";
        }
        field(3; "Calculation Date"; Date)
        {
            Caption = 'Calculation Date';
        }
        field(10; "Vendor No."; Code[20])
        {
            Caption = 'Vendor No.';
            TableRelation = Vendor."No.";
        }
        field(11; "Vendor Name"; Text[100])
        {
            Caption = 'Vendor Name';
            FieldClass = FlowField;
            CalcFormula = lookup(Vendor.Name where("No." = field("Vendor No.")));
            Editable = false;
        }
        field(12; "Vendor Location Code"; Code[20])
        {
            Caption = 'Vendor FOB Location';
            TableRelation = "GPI Pack Vendor Loc".Code where("Vendor No." = field("Vendor No."));
        }
        field(13; "FOB City"; Text[50])
        {
            Caption = 'FOB City';
            FieldClass = FlowField;
            CalcFormula = lookup("GPI Pack Vendor Loc".City where("Vendor No." = field("Vendor No."), Code = field("Vendor Location Code")));
            Editable = false;
        }
        field(14; "FOB State/Province"; Code[20])
        {
            Caption = 'FOB State/Province';
            FieldClass = FlowField;
            CalcFormula = lookup("GPI Pack Vendor Loc"."State/Province" where("Vendor No." = field("Vendor No."), Code = field("Vendor Location Code")));
            Editable = false;
        }
        field(20; "Destination State"; Code[20])
        {
            Caption = 'Destination State';
        }
        field(21; Mode; Enum "GPI Pack Transport")
        {
            Caption = 'Transport Mode';
        }
        field(30; Quantity; Decimal)
        {
            Caption = 'Quantity';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
        }
        field(31; "Gram Weight"; Decimal)
        {
            Caption = 'Gram Weight';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
        }
        field(32; "No. of Pallets"; Decimal)
        {
            Caption = 'No. of Pallets';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
        }
        field(33; "Unit Cost"; Decimal)
        {
            Caption = 'Supplier Unit Cost';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(34; "Pallet Cost per Pallet"; Decimal)
        {
            Caption = 'Pallet Cost per Pallet';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(35; "Shipment CWT"; Decimal)
        {
            Caption = 'Shipment CWT';
            DecimalPlaces = 0 : 5;
            Editable = false;
        }
        field(40; "Use Freight Rate"; Boolean)
        {
            Caption = 'Use Freight Rate';
        }
        field(41; "Freight Rate Entry No."; Integer)
        {
            Caption = 'Freight Rate Entry No.';
            TableRelation = "GPI Pack Frt Rate"."Entry No.";
            Editable = false;
        }
        field(42; "Rate per CWT"; Decimal)
        {
            Caption = 'Rate per CWT';
            AutoFormatType = 2;
            Editable = false;
        }
        field(43; "Minimum Charge"; Decimal)
        {
            Caption = 'Minimum Charge';
            AutoFormatType = 2;
            Editable = false;
        }
        field(44; "Fuel Surcharge %"; Decimal)
        {
            Caption = 'Fuel Surcharge %';
            DecimalPlaces = 0 : 5;
            Editable = false;
        }
        field(45; "Rate Freight Total"; Decimal)
        {
            Caption = 'Rate Freight Total';
            AutoFormatType = 2;
            Editable = false;
        }
        field(46; "Manual Freight Total"; Decimal)
        {
            Caption = 'Manual Freight Total';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(47; "Domestic Freight Total"; Decimal)
        {
            Caption = 'Domestic Freight Total';
            AutoFormatType = 2;
            Editable = false;
        }
        field(50; "Tariff %"; Decimal)
        {
            Caption = 'Tariff %';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
        }
        field(51; "Intl Freight Total"; Decimal)
        {
            Caption = 'International Freight Total';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(52; "Customs Total"; Decimal)
        {
            Caption = 'Customs Total';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(53; "Delivery Charge Total"; Decimal)
        {
            Caption = 'Delivery Charge Total';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(60; "Pallet Cost per Unit"; Decimal)
        {
            Caption = 'Pallet Cost per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(61; "Domestic Frt per Unit"; Decimal)
        {
            Caption = 'Domestic Freight per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(62; "Tariff per Unit"; Decimal)
        {
            Caption = 'Tariff per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(63; "Intl Freight per Unit"; Decimal)
        {
            Caption = 'International Freight per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(64; "Customs per Unit"; Decimal)
        {
            Caption = 'Customs per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(65; "Delivery per Unit"; Decimal)
        {
            Caption = 'Delivery per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(66; "Landed Cost per Unit"; Decimal)
        {
            Caption = 'Landed Cost per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(ProductDate; "Product No.", "Calculation Date", "Entry No.")
        {
        }
    }

    trigger OnInsert()
    begin
        if "Calculation Date" = 0D then
            "Calculation Date" := WorkDate();
    end;
}
