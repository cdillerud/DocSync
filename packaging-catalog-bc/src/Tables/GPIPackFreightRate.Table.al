table 71003 "GPI Pack Freight Rate"
{
    Caption = 'GPI Packaging Freight Rate';
    DataClassification = CustomerContent;
    LookupPageId = "GPI Pack Freight Rates";
    DrillDownPageId = "GPI Pack Freight Rates";

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; "Origin Vendor No."; Code[20])
        {
            Caption = 'Origin Vendor No.';
            TableRelation = Vendor."No.";
        }
        field(3; "Origin Location Code"; Code[20])
        {
            Caption = 'Origin Location Code';
            TableRelation = "GPI Pack Vendor Location".Code where("Vendor No." = field("Origin Vendor No."));
        }
        field(4; "Destination State"; Code[20])
        {
            Caption = 'Destination State';
        }
        field(5; "Default Destination"; Boolean)
        {
            Caption = 'Default Destination';
        }
        field(6; Mode; Enum "GPI Pack Transport Mode")
        {
            Caption = 'Mode';
        }
        field(10; "Rate per CWT"; Decimal)
        {
            Caption = 'Rate per CWT';
            AutoFormatType = 2;
        }
        field(11; "Minimum Charge"; Decimal)
        {
            Caption = 'Minimum Charge';
            AutoFormatType = 2;
        }
        field(12; "Fuel Surcharge %"; Decimal)
        {
            Caption = 'Fuel Surcharge %';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
        }
        field(20; "Effective Date"; Date)
        {
            Caption = 'Effective Date';
        }
        field(21; Notes; Text[250])
        {
            Caption = 'Notes';
        }
        field(30; Blocked; Boolean)
        {
            Caption = 'Blocked';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(RateLookup; "Origin Vendor No.", "Origin Location Code", "Destination State", "Default Destination", Mode, "Effective Date")
        {
        }
    }
}
