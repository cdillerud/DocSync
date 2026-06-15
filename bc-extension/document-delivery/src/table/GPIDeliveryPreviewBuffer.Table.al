table 70150002 "GPI Delivery Preview Buffer"
{
    Caption = 'GPI Delivery Preview Buffer';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
        }
        field(10; "Record No."; Code[20])
        {
            Caption = 'Sales Order No.';
        }
        field(20; "Report ID"; Integer)
        {
            Caption = 'Report ID';
        }
        field(30; "Package ID"; Text[100])
        {
            Caption = 'GPI Hub Package ID';
        }
        field(40; "Correlation ID"; Text[100])
        {
            Caption = 'Correlation ID';
        }
        field(50; Status; Text[50])
        {
            Caption = 'Preflight Status';
        }
        field(60; "From Address"; Text[250])
        {
            Caption = 'From';
        }
        field(70; "To Recipients"; Text[2048])
        {
            Caption = 'To';
        }
        field(80; "CC Recipients"; Text[2048])
        {
            Caption = 'CC';
        }
        field(90; "BCC Recipients"; Text[2048])
        {
            Caption = 'BCC';
        }
        field(100; Subject; Text[2048])
        {
            Caption = 'Subject';
        }
        field(110; Body; Text[2048])
        {
            Caption = 'Email Body';
        }
        field(120; "File Name"; Text[250])
        {
            Caption = 'Attachment File Name';
        }
        field(130; "Archive Path"; Text[500])
        {
            Caption = 'Planned SharePoint Path';
        }
        field(140; "Routing Rule"; Text[100])
        {
            Caption = 'Routing Rule';
        }
        field(150; Warnings; Text[2048])
        {
            Caption = 'Warnings';
        }
        field(160; "Can Create Draft"; Boolean)
        {
            Caption = 'Can Create Draft';
        }
        field(170; Duplicate; Boolean)
        {
            Caption = 'Existing Package Reused';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
    }
}
