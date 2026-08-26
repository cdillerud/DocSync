table 71121 "GPI Comm Evidence"
{
    Caption = 'GPI Commercial Evidence';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; "Exception Entry No."; Integer)
        {
            Caption = 'Exception Entry No.';
            TableRelation = "GPI Comm Exception"."Entry No.";
        }
        field(3; "Evidence Type"; Text[50])
        {
            Caption = 'Evidence Type';
        }
        field(4; "Source System"; Text[30])
        {
            Caption = 'Source System';
        }
        field(5; "Source Record Type"; Text[50])
        {
            Caption = 'Source Record Type';
        }
        field(6; "Source SystemId"; Guid)
        {
            Caption = 'Source SystemId';
        }
        field(7; Metric; Code[50])
        {
            Caption = 'Metric';
        }
        field(8; "Current Value"; Text[250])
        {
            Caption = 'Current Value';
        }
        field(9; "Comparison Value"; Text[250])
        {
            Caption = 'Comparison Value';
        }
        field(10; Variance; Decimal)
        {
            Caption = 'Variance';
            DecimalPlaces = 0 : 5;
        }
        field(11; Unit; Code[20])
        {
            Caption = 'Unit';
        }
        field(12; Weight; Decimal)
        {
            Caption = 'Weight';
            MinValue = 0;
            MaxValue = 100;
            DecimalPlaces = 0 : 2;
        }
        field(13; Explanation; Text[1024])
        {
            Caption = 'Explanation';
        }
        field(14; Provenance; Text[250])
        {
            Caption = 'Provenance';
        }
        field(15; "Captured At"; DateTime)
        {
            Caption = 'Captured At';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(Exception; "Exception Entry No.", "Entry No.")
        {
        }
        key(Metric; "Exception Entry No.", Metric)
        {
        }
    }
}
