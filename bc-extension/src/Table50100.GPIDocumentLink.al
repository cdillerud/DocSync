/// <summary>
/// Table 50100 "GPI Document Link"
/// Stores SharePoint document links for BC records.
/// Used by GPI Document Hub to link uploaded documents to Purchase Invoices.
/// </summary>
table 50100 "GPI Document Link"
{
    Caption = 'GPI Document Link';
    DataClassification = CustomerContent;
    LookupPageId = "GPI Document Link List";
    DrillDownPageId = "GPI Document Link List";

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
            Editable = false;
        }
        field(10; "Document Type"; Enum "GPI Doc Link Type")
        {
            Caption = 'Document Type';
        }
        field(20; "Target SystemId"; Guid)
        {
            Caption = 'Target System ID';
            Description = 'SystemId of the target BC record (e.g., Purchase Invoice)';
        }
        field(30; "BC Document No."; Code[20])
        {
            Caption = 'BC Document No.';
            Description = 'Optional display field for the BC document number';
        }
        field(100; "SharePoint Url"; Text[2048])
        {
            Caption = 'SharePoint URL';
            ExtendedDatatype = URL;
        }
        field(110; "SharePoint Drive Id"; Text[200])
        {
            Caption = 'SharePoint Drive ID';
        }
        field(120; "SharePoint Item Id"; Text[200])
        {
            Caption = 'SharePoint Item ID';
        }
        field(200; "Uploaded At"; DateTime)
        {
            Caption = 'Uploaded At';
        }
        field(210; "Uploaded By"; Text[100])
        {
            Caption = 'Uploaded By';
        }
        field(220; "Source"; Enum "GPI Doc Link Source")
        {
            Caption = 'Source';
        }
        field(230; "Last Error"; Text[250])
        {
            Caption = 'Last Error';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(DocumentKey; "Document Type", "Target SystemId")
        {
            Unique = true;
        }
        key(BCDocNo; "Document Type", "BC Document No.")
        {
        }
    }

    trigger OnInsert()
    begin
        if "Uploaded At" = 0DT then
            "Uploaded At" := CurrentDateTime();
    end;
}
