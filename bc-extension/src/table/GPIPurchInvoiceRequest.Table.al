table 50103 "GPI Purch. Invoice Request"
{
    Caption = 'GPI Purchase Invoice Request';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(10; "Idempotency Key"; Code[100])
        {
            Caption = 'Idempotency Key';
        }
        field(11; "Source System"; Code[50])
        {
            Caption = 'Source System';
        }
        field(12; "Source Document ID"; Code[100])
        {
            Caption = 'Source Document ID';
        }
        field(13; "Transaction ID"; Code[100])
        {
            Caption = 'Transaction ID';
        }
        field(20; "Vendor No."; Code[20])
        {
            Caption = 'Vendor No.';
        }
        field(21; "Vendor Invoice No."; Code[35])
        {
            Caption = 'Vendor Invoice No.';
        }
        field(22; "Document Date"; Text[30])
        {
            Caption = 'Document Date';
        }
        field(23; "Posting Date"; Text[30])
        {
            Caption = 'Posting Date';
        }
        field(50; "Result Record No."; Code[20])
        {
            Caption = 'Result Record No.';
            Editable = false;
        }
        field(51; "Result System ID"; Guid)
        {
            Caption = 'Result System ID';
            Editable = false;
        }
        field(52; "Result Status"; Text[50])
        {
            Caption = 'Result Status';
            Editable = false;
        }
        field(53; "Result Success"; Boolean)
        {
            Caption = 'Result Success';
            Editable = false;
        }
        field(54; "Error Message"; Text[2048])
        {
            Caption = 'Error Message';
            Editable = false;
        }
        field(60; "Created DateTime"; DateTime)
        {
            Caption = 'Created DateTime';
            Editable = false;
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(IdempotencyKey; "Idempotency Key")
        {
        }
    }

    trigger OnInsert()
    begin
        "Created DateTime" := CurrentDateTime;
    end;
}
