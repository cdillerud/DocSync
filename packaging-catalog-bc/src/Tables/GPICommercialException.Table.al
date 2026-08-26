table 71120 "GPI Commercial Exception"
{
    Caption = 'GPI Commercial Exception';
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
        field(3; "Detected At"; DateTime)
        {
            Caption = 'Detected At';
        }
        field(4; "Source Type"; Text[50])
        {
            Caption = 'Source Type';
        }
        field(5; "Source SystemId"; Guid)
        {
            Caption = 'Source SystemId';
        }
        field(6; "Source Key"; Text[100])
        {
            Caption = 'Source Key';
        }
        field(7; "Customer No."; Code[20])
        {
            Caption = 'Customer No.';
            TableRelation = Customer."No.";
        }
        field(8; "Item No."; Code[20])
        {
            Caption = 'Item No.';
            TableRelation = Item."No.";
        }
        field(9; "Document Type"; Text[30])
        {
            Caption = 'Document Type';
        }
        field(10; "Document No."; Code[20])
        {
            Caption = 'Document No.';
        }
        field(11; Severity; Integer)
        {
            Caption = 'Severity';
            MinValue = 0;
            MaxValue = 100;
        }
        field(12; "Risk Score"; Decimal)
        {
            Caption = 'Risk Score';
            MinValue = 0;
            MaxValue = 100;
            DecimalPlaces = 0 : 2;
        }
        field(13; "Confidence Score"; Decimal)
        {
            Caption = 'Confidence Score';
            MinValue = 0;
            MaxValue = 100;
            DecimalPlaces = 0 : 2;
        }
        field(14; Status; Enum "GPI Commercial Ex Status")
        {
            Caption = 'Status';
        }
        field(15; "Assigned To"; Text[100])
        {
            Caption = 'Assigned To';
        }
        field(16; Summary; Text[250])
        {
            Caption = 'Summary';
        }
        field(17; Finding; Text[2048])
        {
            Caption = 'Finding';
        }
        field(18; "Recommended Action"; Text[2048])
        {
            Caption = 'Recommended Action';
        }
        field(19; "Decision Note"; Text[2048])
        {
            Caption = 'Decision Note';
        }
        field(20; "AI Model"; Text[100])
        {
            Caption = 'AI Model';
        }
        field(21; "Evaluation Version"; Code[20])
        {
            Caption = 'Evaluation Version';
        }
        field(22; "Correlation ID"; Guid)
        {
            Caption = 'Correlation ID';
        }
        field(23; "Created At"; DateTime)
        {
            Caption = 'Created At';
        }
        field(24; "Updated At"; DateTime)
        {
            Caption = 'Updated At';
        }
        field(25; "Reviewed By"; Text[100])
        {
            Caption = 'Reviewed By';
        }
        field(26; "Reviewed At"; DateTime)
        {
            Caption = 'Reviewed At';
        }
        field(27; Disposition; Text[50])
        {
            Caption = 'Disposition';
        }
        field(28; "False Positive"; Boolean)
        {
            Caption = 'False Positive';
        }
        field(29; "Queue Entry No."; Integer)
        {
            Caption = 'Queue Entry No.';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(Source; "Agent Type", "Source Type", "Source Key")
        {
        }
        key(Customer; "Customer No.", "Detected At")
        {
        }
        key(Item; "Item No.", "Detected At")
        {
        }
        key(Status; Status, Severity, "Detected At")
        {
        }
    }
}
