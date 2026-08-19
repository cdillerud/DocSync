table 71013 "GPI Item Field Meta"
{
    Caption = 'GPI BC Item Field Metadata';
    DataClassification = SystemMetadata;
    DataPerCompany = false;

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
        field(5; Length; Integer)
        {
            Caption = 'Length';
        }
        field(6; "Field Class"; Text[30])
        {
            Caption = 'Field Class';
        }
        field(7; Enabled; Boolean)
        {
            Caption = 'Enabled';
        }
        field(8; "Type Name"; Text[30])
        {
            Caption = 'Type Name';
        }
        field(9; "External Name"; Text[100])
        {
            Caption = 'External Name';
        }
        field(10; "Relation Table No."; Integer)
        {
            Caption = 'Relation Table No.';
        }
        field(11; "Relation Field No."; Integer)
        {
            Caption = 'Relation Field No.';
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
    }
}
