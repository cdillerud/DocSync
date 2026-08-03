table 70513 "GPI SharePoint Archive Setup"
{
    Caption = 'GPI SharePoint Archive Setup';
    DataClassification = SystemMetadata;
    DataPerCompany = true;

    fields
    {
        field(1; "Primary Key"; Code[10])
        {
            Caption = 'Primary Key';
            DataClassification = SystemMetadata;
        }
        field(2; Enabled; Boolean)
        {
            Caption = 'Enabled';
            DataClassification = SystemMetadata;
        }
        field(5; "SharePoint Web Base URL"; Text[250])
        {
            Caption = 'SharePoint Web Base URL';
            DataClassification = OrganizationIdentifiableInformation;
            ExtendedDatatype = URL;
        }
        field(7; "Root Folder"; Text[250])
        {
            Caption = 'Root Folder';
            DataClassification = OrganizationIdentifiableInformation;
        }
        field(8; "Sales Folder"; Text[50])
        {
            Caption = 'Sales Folder';
            DataClassification = OrganizationIdentifiableInformation;
        }
        field(9; "Purchase Folder"; Text[50])
        {
            Caption = 'Purchase Folder';
            DataClassification = OrganizationIdentifiableInformation;
        }
        field(10; "Clear Local PDF After Archive"; Boolean)
        {
            Caption = 'Clear Local PDF After Archive';
            DataClassification = SystemMetadata;
        }
        field(11; "Last Connection Test"; DateTime)
        {
            Caption = 'Last Connection Test';
            DataClassification = SystemMetadata;
        }
        field(12; "Last Connection Result"; Text[2048])
        {
            Caption = 'Last Connection Result';
            DataClassification = SystemMetadata;
        }
    }

    keys
    {
        key(PK; "Primary Key")
        {
            Clustered = true;
        }
    }

    trigger OnInsert()
    begin
        if "Primary Key" = '' then
            "Primary Key" := 'SETUP';
        if "SharePoint Web Base URL" = '' then
            "SharePoint Web Base URL" := 'https://gamerpackaging1.sharepoint.com/sites/DocsNAV/Zetadocs';
        if "Sales Folder" = '' then
            "Sales Folder" := 'Sales';
        if "Purchase Folder" = '' then
            "Purchase Folder" := 'Purchase';
        "Clear Local PDF After Archive" := true;
    end;
}
