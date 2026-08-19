table 71014 "GPI Item Field Stat"
{
    Caption = 'GPI BC Item Field Profile';
    DataClassification = SystemMetadata;

    fields
    {
        field(1; "Field No."; Integer)
        {
            Caption = 'Field No.';
        }
        field(2; "Field Name"; Text[30])
        {
            Caption = 'Field Name';
        }
        field(3; "Field Caption"; Text[80])
        {
            Caption = 'Field Caption';
        }
        field(4; "Data Type"; Text[30])
        {
            Caption = 'Data Type';
        }
        field(5; "Total Item Count"; Integer)
        {
            Caption = 'Total Item Count';
        }
        field(6; "Nondefault Count"; Integer)
        {
            Caption = 'Nondefault Count';
        }
        field(7; "Nondefault Percent"; Decimal)
        {
            Caption = 'Nondefault Percent';
            DecimalPlaces = 0 : 2;
        }
        field(8; "Sample Values"; Text[2048])
        {
            Caption = 'Sample Values';
        }
        field(9; "Sample Item Nos."; Text[500])
        {
            Caption = 'Sample Item Nos.';
        }
        field(10; "Packaging Relevant"; Boolean)
        {
            Caption = 'Packaging Relevant';
        }
        field(11; "Matched Keyword"; Text[30])
        {
            Caption = 'Matched Keyword';
        }
        field(20; "Scanned At"; DateTime)
        {
            Caption = 'Scanned At';
        }
    }

    keys
    {
        key(PK; "Field No.")
        {
            Clustered = true;
        }
        key(Relevance; "Packaging Relevant", "Nondefault Count", "Field No.")
        {
        }
    }
}
