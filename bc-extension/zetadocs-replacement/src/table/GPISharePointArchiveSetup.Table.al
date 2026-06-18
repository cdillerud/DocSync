table 70512 "GPI SharePoint Archive Setup"
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
        field(3; "Tenant ID"; Text[100])
        {
            Caption = 'Tenant ID';
            DataClassification = OrganizationIdentifiableInformation;
        }
        field(4; "Client ID"; Text[100])
        {
            Caption = 'Client ID';
            DataClassification = OrganizationIdentifiableInformation;
        }
        field(5; "SharePoint Site URL"; Text[250])
        {
            Caption = 'SharePoint Site URL';
            DataClassification = OrganizationIdentifiableInformation;
            ExtendedDatatype = URL;
        }
        field(6; "Drive ID"; Text[250])
        {
            Caption = 'Drive ID';
            DataClassification = OrganizationIdentifiableInformation;
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
        if "Tenant ID" = '' then
            "Tenant ID" := 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc';
        if "SharePoint Site URL" = '' then
            "SharePoint Site URL" := 'https://gamerpackaging1.sharepoint.com/sites/DocsNAV';
        if "Drive ID" = '' then
            "Drive ID" := 'b!sGwtDnGpU0SknFYQW3UCWWUMVN5OAqNNqrsMXnSKBw-YAHZMq-H6QZCZOp4jgXfD';
        if "Root Folder" = '' then
            "Root Folder" := 'Zetadocs';
        if "Sales Folder" = '' then
            "Sales Folder" := 'Sales';
        if "Purchase Folder" = '' then
            "Purchase Folder" := 'Purchase';
        "Clear Local PDF After Archive" := true;
    end;
}
