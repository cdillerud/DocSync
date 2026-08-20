table 71101 "GPI Pack Product Doc"
{
    Caption = 'Packaging Product Document';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; "Product No."; Code[20])
        {
            Caption = 'Product No.';
            TableRelation = "GPI Pack Product"."No.";
            NotBlank = true;
        }
        field(3; "Document Type"; Enum "GPI Pack Doc Type")
        {
            Caption = 'Document Type';
        }
        field(4; Description; Text[100])
        {
            Caption = 'Description';
        }
        field(5; "File Name"; Text[250])
        {
            Caption = 'File Name';
            Editable = false;
        }
        field(6; Content; Blob)
        {
            Caption = 'Content';
            DataClassification = CustomerContent;
        }
        field(7; "Uploaded At"; DateTime)
        {
            Caption = 'Uploaded At';
            Editable = false;
        }
        field(8; "Uploaded By"; Text[100])
        {
            Caption = 'Uploaded By';
            Editable = false;
        }
        field(9; "Primary Document"; Boolean)
        {
            Caption = 'Primary Document';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(Product; "Product No.", "Document Type", "Entry No.")
        {
        }
    }
}
