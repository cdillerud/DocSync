table 71012 "GPI Route Cache"
{
    Caption = 'GPI Packaging Route Cache';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; "Origin Latitude"; Decimal)
        {
            Caption = 'Origin Latitude';
            DecimalPlaces = 0 : 8;
        }
        field(3; "Origin Longitude"; Decimal)
        {
            Caption = 'Origin Longitude';
            DecimalPlaces = 0 : 8;
        }
        field(4; "Destination Latitude"; Decimal)
        {
            Caption = 'Destination Latitude';
            DecimalPlaces = 0 : 8;
        }
        field(5; "Destination Longitude"; Decimal)
        {
            Caption = 'Destination Longitude';
            DecimalPlaces = 0 : 8;
        }
        field(6; Mode; Enum "GPI Pack Transport")
        {
            Caption = 'Transport Mode';
        }
        field(7; "Distance Miles"; Decimal)
        {
            Caption = 'Route Distance Miles';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
        }
        field(8; "Duration Minutes"; Decimal)
        {
            Caption = 'Route Duration Minutes';
            DecimalPlaces = 0 : 2;
            MinValue = 0;
        }
        field(9; Provider; Enum "GPI Route Provider")
        {
            Caption = 'Route Provider';
        }
        field(10; "Calculated At"; DateTime)
        {
            Caption = 'Calculated At';
        }
        field(11; "Expires At"; DateTime)
        {
            Caption = 'Expires At';
        }
        field(12; "Provider Reference"; Text[100])
        {
            Caption = 'Provider Reference';
        }
        field(13; Notes; Text[250])
        {
            Caption = 'Notes';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(RouteLookup; "Origin Latitude", "Origin Longitude", "Destination Latitude", "Destination Longitude", Mode, "Expires At")
        {
        }
    }
}
