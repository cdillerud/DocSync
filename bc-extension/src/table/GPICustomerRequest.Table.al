table 50104 "GPI Customer Request"
{
    Caption = 'GPI Customer Request';
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
        field(20; "Name"; Text[100])
        {
            Caption = 'Name';
        }
        field(21; "Address"; Text[100])
        {
            Caption = 'Address';
        }
        field(22; "City"; Text[30])
        {
            Caption = 'City';
        }
        field(23; "State Code"; Code[10])
        {
            Caption = 'State Code';
        }
        field(24; "Postal Code"; Code[20])
        {
            Caption = 'Postal Code';
        }
        field(25; "Country Code"; Code[10])
        {
            Caption = 'Country Code';
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
