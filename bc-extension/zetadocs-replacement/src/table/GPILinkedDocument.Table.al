table 70514 "GPI Linked Document"
{
    Caption = 'GPI Linked Document';
    DataClassification = CustomerContent;
    DataPerCompany = true;

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
            DataClassification = SystemMetadata;
        }
        field(2; "Source Table ID"; Integer)
        {
            Caption = 'Source Table ID';
            DataClassification = SystemMetadata;
        }
        field(3; "Source System ID"; Guid)
        {
            Caption = 'Source System ID';
            DataClassification = SystemMetadata;
        }
        field(4; "Source Document Type"; Text[50])
        {
            Caption = 'Source Document Type';
            DataClassification = CustomerContent;
        }
        field(5; "Source Document No."; Code[50])
        {
            Caption = 'Source Document No.';
            DataClassification = CustomerContent;
        }
        field(6; "Source Party No."; Code[20])
        {
            Caption = 'Source Party No.';
            DataClassification = CustomerContent;
        }
        field(7; "Source Party Name"; Text[100])
        {
            Caption = 'Source Party Name';
            DataClassification = CustomerContent;
        }
        field(8; "Business Area"; Text[20])
        {
            Caption = 'Business Area';
            DataClassification = CustomerContent;
        }
        field(10; "File Name"; Text[250])
        {
            Caption = 'File Name';
            DataClassification = CustomerContent;
        }
        field(11; "Content Type"; Text[100])
        {
            Caption = 'Content Type';
            DataClassification = CustomerContent;
        }
        field(12; "File Size"; BigInteger)
        {
            Caption = 'File Size';
            DataClassification = SystemMetadata;
        }
        field(13; "Archive Path"; Text[2048])
        {
            Caption = 'Archive Path';
            DataClassification = OrganizationIdentifiableInformation;
        }
        field(14; "SharePoint URL"; Text[2048])
        {
            Caption = 'SharePoint URL';
            DataClassification = OrganizationIdentifiableInformation;
            ExtendedDatatype = URL;
        }
        field(15; "Uploaded By"; Text[100])
        {
            Caption = 'Uploaded By';
            DataClassification = EndUserIdentifiableInformation;
        }
        field(16; "Uploaded Date/Time"; DateTime)
        {
            Caption = 'Uploaded Date/Time';
            DataClassification = SystemMetadata;
        }
        field(17; Description; Text[250])
        {
            Caption = 'Description';
            DataClassification = CustomerContent;
        }
        field(18; Category; Text[50])
        {
            Caption = 'Category';
            DataClassification = CustomerContent;
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(Source; "Source Table ID", "Source System ID", "Uploaded Date/Time")
        {
        }
    }
}
