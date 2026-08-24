table 71106 "GPI Spiro Push Queue"
{
    Caption = 'GPI Spiro Push Queue';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; "Quote No."; Integer)
        {
            Caption = 'Quote No.';
        }
        field(3; "Spiro Opportunity ID"; Text[100])
        {
            Caption = 'Spiro Opportunity ID';
        }
        field(4; Status; Text[30])
        {
            Caption = 'Status';
        }
        field(5; "Requested At"; DateTime)
        {
            Caption = 'Requested At';
        }
        field(6; "Requested By"; Text[100])
        {
            Caption = 'Requested By';
        }
        field(7; "Processed At"; DateTime)
        {
            Caption = 'Processed At';
        }
        field(8; Message; Text[250])
        {
            Caption = 'Message';
        }        field(9; "Attempt Count"; Integer)
        {
            Caption = 'Attempt Count';
        }
        field(10; "Last Attempt At"; DateTime)
        {
            Caption = 'Last Attempt At';
        }
        field(11; "Next Attempt At"; DateTime)
        {
            Caption = 'Next Attempt At';
        }
        field(12; "Last Error"; Text[250])
        {
            Caption = 'Last Error';
        }
        field(13; "Worker ID"; Text[100])
        {
            Caption = 'Worker ID';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(QuoteStatus; "Quote No.", Status)
        {
        }
    }
}