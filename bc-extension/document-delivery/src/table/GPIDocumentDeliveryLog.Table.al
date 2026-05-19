table 70150001 "GPI Doc Delivery Log"
{
    Caption = 'GPI Document Delivery Log';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(10; "Event ID"; Text[100])
        {
            Caption = 'Event ID';
        }
        field(20; "Event Type"; Text[50])
        {
            Caption = 'Event Type';
        }
        field(30; "Correlation ID"; Text[100])
        {
            Caption = 'Correlation ID';
        }
        field(40; "BC Record Type"; Text[100])
        {
            Caption = 'BC Record Type';
        }
        field(50; "BC Record No."; Code[50])
        {
            Caption = 'BC Record No.';
        }
        field(60; "Document Type"; Text[50])
        {
            Caption = 'Document Type';
        }
        field(70; "File Name"; Text[250])
        {
            Caption = 'File Name';
        }
        field(80; "Endpoint"; Text[250])
        {
            Caption = 'Endpoint';
        }
        field(90; "HTTP Status Code"; Integer)
        {
            Caption = 'HTTP Status Code';
        }
        field(100; Success; Boolean)
        {
            Caption = 'Success';
        }
        field(110; Duplicate; Boolean)
        {
            Caption = 'Duplicate';
        }
        field(120; "Hub Document ID"; Text[100])
        {
            Caption = 'Hub Document ID';
        }
        field(130; "Response Body"; Blob)
        {
            Caption = 'Response Body';
        }
        field(140; "Error Message"; Text[500])
        {
            Caption = 'Error Message';
        }
        field(150; "Created At"; DateTime)
        {
            Caption = 'Created At';
        }
        field(160; "Created By"; Text[100])
        {
            Caption = 'Created By';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(EventID; "Event ID") { }
        key(BCRecord; "BC Record Type", "BC Record No.") { }
        key(CreatedAt; "Created At") { }
    }

    procedure SetResponseBody(ResponseText: Text)
    var
        OutStream: OutStream;
    begin
        Clear("Response Body");
        "Response Body".CreateOutStream(OutStream, TextEncoding::UTF8);
        OutStream.WriteText(ResponseText);
    end;

    procedure GetResponseBody() ResponseText: Text
    var
        InStream: InStream;
    begin
        CalcFields("Response Body");
        if not "Response Body".HasValue then
            exit('');

        "Response Body".CreateInStream(InStream, TextEncoding::UTF8);
        InStream.ReadText(ResponseText);
    end;
}
