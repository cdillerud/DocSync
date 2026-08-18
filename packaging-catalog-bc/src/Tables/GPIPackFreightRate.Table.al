table 71003 "GPI Pack Frt Rate"
{
    Caption = 'GPI Packaging Freight Rate';
    DataClassification = CustomerContent;
    LookupPageId = "GPI Pack Frt Rates";
    DrillDownPageId = "GPI Pack Frt Rates";

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

            trigger OnValidate()
            begin
                if "Origin Vendor No." <> xRec."Origin Vendor No." then
                    "Origin Location Code" := '';
            end;
        }
        field(3; "Origin Location Code"; Code[20])
        {
            Caption = 'Origin Location Code';
            TableRelation = "GPI Pack Vendor Loc".Code where("Vendor No." = field("Origin Vendor No."));
        }
        field(4; "Destination State"; Code[20])
        {
            Caption = 'Destination State';

            trigger OnValidate()
            begin
                if "Destination State" <> '' then
                    "Default Destination" := false;
            end;
        }
        field(5; "Default Destination"; Boolean)
        {
            Caption = 'Default Destination';

            trigger OnValidate()
            begin
                if "Default Destination" then
                    "Destination State" := '';
            end;
        }
        field(6; Mode; Enum "GPI Pack Transport")
        {
            Caption = 'Mode';
        }
        field(10; "Rate per CWT"; Decimal)
        {
            Caption = 'Rate per CWT';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(11; "Minimum Charge"; Decimal)
        {
            Caption = 'Minimum Charge';
            AutoFormatType = 2;
            MinValue = 0;
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
