table 50101 "GPI Integration Log"
{
    Caption = 'GPI Integration Log';
    DataClassification = CustomerContent;
    // LookupPageId temporarily removed — API page excluded from compilation

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
        field(20; "Record Type"; Enum "GPI Record Type")
        {
            Caption = 'Record Type';
        }
        field(30; "Request Status"; Enum "GPI Request Status")
        {
            Caption = 'Request Status';
        }
        field(31; Success; Boolean)
        {
            Caption = 'Success';
        }
        field(40; "BC Record No."; Code[20])
        {
            Caption = 'BC Record No.';
        }
        field(41; "BC System ID"; Guid)
        {
            Caption = 'BC System ID';
        }
        field(42; "Idempotency Status"; Text[50])
        {
            Caption = 'Idempotency Status';
        }
        field(50; "Error Message"; Text[2048])
        {
            Caption = 'Error Message';
        }
        field(60; "Request Payload"; Blob)
        {
            Caption = 'Request Payload';
            Subtype = Json;
        }
        field(70; "Created DateTime"; DateTime)
        {
            Caption = 'Created DateTime';
        }
        field(71; "Created By Integration"; Code[50])
        {
            Caption = 'Created By Integration';
        }
        field(80; "Processing Duration MS"; Integer)
        {
            Caption = 'Processing Duration (ms)';
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
        key(SourceDoc; "Source Document ID", "Record Type")
        {
        }
        key(TransactionLookup; "Transaction ID")
        {
        }
    }
}
