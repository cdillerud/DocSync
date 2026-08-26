table 71122 "GPI Commercial Agent Queue"
{
    Caption = 'GPI Commercial Agent Queue';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; "Agent Type"; Enum "GPI Commercial Agent Type")
        {
            Caption = 'Agent Type';
        }
        field(3; "Source Type"; Text[50])
        {
            Caption = 'Source Type';
        }
        field(4; "Source SystemId"; Guid)
        {
            Caption = 'Source SystemId';
        }
        field(5; "Source Key"; Text[100])
        {
            Caption = 'Source Key';
        }
        field(6; "Customer No."; Code[20])
        {
            Caption = 'Customer No.';
            TableRelation = Customer."No.";
        }
        field(7; "Item No."; Code[20])
        {
            Caption = 'Item No.';
            TableRelation = Item."No.";
        }
        field(8; "Document Type"; Text[30])
        {
            Caption = 'Document Type';
        }
        field(9; "Document No."; Code[20])
        {
            Caption = 'Document No.';
        }
        field(10; Status; Enum "GPI Agent Queue Status")
        {
            Caption = 'Status';
        }
        field(11; Priority; Integer)
        {
            Caption = 'Priority';
        }
        field(12; "Requested At"; DateTime)
        {
            Caption = 'Requested At';
        }
        field(13; "Started At"; DateTime)
        {
            Caption = 'Started At';
        }
        field(14; "Completed At"; DateTime)
        {
            Caption = 'Completed At';
        }
        field(15; "Attempt Count"; Integer)
        {
            Caption = 'Attempt Count';
            MinValue = 0;
        }
        field(16; "Max Attempts"; Integer)
        {
            Caption = 'Max Attempts';
            MinValue = 1;
            InitValue = 3;
        }
        field(17; "Next Attempt At"; DateTime)
        {
            Caption = 'Next Attempt At';
        }
        field(18; "Exception Entry No."; Integer)
        {
            Caption = 'Exception Entry No.';
            TableRelation = "GPI Commercial Exception"."Entry No.";
        }
        field(19; "Last Error"; Text[2048])
        {
            Caption = 'Last Error';
        }
        field(20; "Correlation ID"; Guid)
        {
            Caption = 'Correlation ID';
        }
        field(21; "Idempotency Key"; Text[100])
        {
            Caption = 'Idempotency Key';
        }
        field(22; "Requested By"; Text[100])
        {
            Caption = 'Requested By';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(StatusPriority; Status, Priority, "Requested At")
        {
        }
        key(Source; "Agent Type", "Source Type", "Source Key", Status)
        {
        }
        key(Idempotency; "Agent Type", "Idempotency Key", Status)
        {
        }
    }
}
