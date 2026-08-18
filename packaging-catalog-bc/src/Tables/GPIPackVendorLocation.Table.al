table 71001 "GPI Pack Vendor Loc"
{
    Caption = 'GPI Packaging Vendor Location';
    DataClassification = CustomerContent;
    LookupPageId = "GPI Pack Vendor Locs";
    DrillDownPageId = "GPI Pack Vendor Locs";

    fields
    {
        field(1; "Vendor No."; Code[20])
        {
            Caption = 'Vendor No.';
            TableRelation = Vendor."No.";
            NotBlank = true;
        }
        field(2; Code; Code[20])
        {
            Caption = 'Location Code';
            NotBlank = true;
        }
        field(3; Description; Text[100])
        {
            Caption = 'Description';
        }
        field(10; Address; Text[100])
        {
            Caption = 'Address';
        }
        field(11; "Address 2"; Text[50])
        {
            Caption = 'Address 2';
        }
        field(12; City; Text[50])
        {
            Caption = 'City';
        }
        field(13; "State/Province"; Code[20])
        {
            Caption = 'State/Province';
        }
        field(14; "Post Code"; Code[20])
        {
            Caption = 'Post Code';
        }
        field(15; "Country/Region Code"; Code[10])
        {
            Caption = 'Country/Region Code';
            TableRelation = "Country/Region".Code;
        }
        field(20; Latitude; Decimal)
        {
            Caption = 'Latitude';
            DecimalPlaces = 0 : 8;
        }
        field(21; Longitude; Decimal)
        {
            Caption = 'Longitude';
            DecimalPlaces = 0 : 8;
        }
        field(30; "Default FOB"; Boolean)
        {
            Caption = 'Default FOB';
        }
        field(31; Blocked; Boolean)
        {
            Caption = 'Blocked';
        }
    }

    keys
    {
        key(PK; "Vendor No.", Code)
        {
            Clustered = true;
        }
        key(DefaultFOB; "Vendor No.", "Default FOB")
        {
        }
    }
}
