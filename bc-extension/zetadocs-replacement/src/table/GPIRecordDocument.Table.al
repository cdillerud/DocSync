table 70620 "GPI Record Document"
{
    Caption = 'GPI Record Document';
    DataClassification = CustomerContent;
    DataPerCompany = true;

    fields
    {
        field(1; "Entry No."; Integer) { Caption = 'Entry No.'; AutoIncrement = true; DataClassification = SystemMetadata; }
        field(2; "Source Table ID"; Integer) { Caption = 'Source Table ID'; DataClassification = SystemMetadata; }
        field(3; "Source SystemId"; Guid) { Caption = 'Source SystemId'; DataClassification = SystemMetadata; }
        field(4; "Source Document Type"; Text[50]) { Caption = 'Source Document Type'; DataClassification = CustomerContent; }
        field(5; "Source Document No."; Code[20]) { Caption = 'Source Document No.'; DataClassification = CustomerContent; }
        field(6; "Source Party Type"; Text[20]) { Caption = 'Source Party Type'; DataClassification = CustomerContent; }
        field(7; "Source Party No."; Code[20]) { Caption = 'Source Party No.'; DataClassification = CustomerContent; }
        field(8; "Customer No."; Code[20]) { Caption = 'Customer No.'; TableRelation = Customer; DataClassification = CustomerContent; }
        field(9; "Vendor No."; Code[20]) { Caption = 'Vendor No.'; TableRelation = Vendor; DataClassification = CustomerContent; }
        field(10; "Location Code"; Code[10]) { Caption = 'Location Code'; TableRelation = Location; DataClassification = CustomerContent; }
        field(11; "Original File Name"; Text[250]) { Caption = 'Original File Name'; DataClassification = CustomerContent; }
        field(12; "SharePoint File Name"; Text[250]) { Caption = 'SharePoint File Name'; DataClassification = CustomerContent; }
        field(13; "SharePoint Path"; Text[2048]) { Caption = 'SharePoint Path'; DataClassification = CustomerContent; }
        field(14; "SharePoint URL"; Text[2048]) { Caption = 'SharePoint URL'; ExtendedDatatype = URL; DataClassification = CustomerContent; }
        field(15; "SharePoint Item ID"; Text[250]) { Caption = 'SharePoint Item ID'; DataClassification = SystemMetadata; }
        field(16; "Content Type"; Text[100]) { Caption = 'Content Type'; DataClassification = CustomerContent; }
        field(17; "File Size"; BigInteger) { Caption = 'File Size'; DataClassification = SystemMetadata; }
        field(18; Category; Text[50]) { Caption = 'Category'; DataClassification = CustomerContent; }
        field(19; Description; Text[250]) { Caption = 'Description'; DataClassification = CustomerContent; }
        field(20; "Uploaded By"; Text[100]) { Caption = 'Uploaded By'; DataClassification = EndUserIdentifiableInformation; }
        field(21; "Uploaded Date/Time"; DateTime) { Caption = 'Uploaded Date/Time'; DataClassification = SystemMetadata; }
        field(22; Status; Enum "GPI Record Document Status") { Caption = 'Status'; DataClassification = SystemMetadata; }
        field(23; "Last Error"; Text[2048]) { Caption = 'Last Error'; DataClassification = CustomerContent; }
    }

    keys
    {
        key(PK; "Entry No.") { Clustered = true; }
        key(Source; "Source Table ID", "Source SystemId", "Uploaded Date/Time") { }
    }

    fieldgroups
    {
        fieldgroup(DropDown; "Original File Name", Category, "Uploaded Date/Time", Status) { }
    }
}
