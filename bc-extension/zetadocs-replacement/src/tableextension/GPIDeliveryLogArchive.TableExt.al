tableextension 70516 "GPI Delivery Log Archive" extends "GPI Document Delivery Log"
{
    fields
    {
        field(70510; "Archive Status"; Enum "GPI Archive Status")
        {
            Caption = 'Archive Status';
            DataClassification = CustomerContent;
        }
        field(70511; "Archived Date/Time"; DateTime)
        {
            Caption = 'Archived Date/Time';
            DataClassification = SystemMetadata;
        }
        field(70512; "SharePoint Drive ID"; Text[250])
        {
            Caption = 'SharePoint Drive ID';
            DataClassification = SystemMetadata;
        }
        field(70513; "SharePoint Item ID"; Text[250])
        {
            Caption = 'SharePoint Item ID';
            DataClassification = SystemMetadata;
        }
        field(70514; "Archive Path"; Text[2048])
        {
            Caption = 'Archive Path';
            DataClassification = OrganizationIdentifiableInformation;
        }
        field(70515; "Archive Attempt Count"; Integer)
        {
            Caption = 'Archive Attempt Count';
            DataClassification = SystemMetadata;
        }
        field(70516; "Last Archive Error"; Text[2048])
        {
            Caption = 'Last Archive Error';
            DataClassification = CustomerContent;
        }
        field(70517; "Last Archive Attempt"; DateTime)
        {
            Caption = 'Last Archive Attempt';
            DataClassification = SystemMetadata;
        }
        field(70518; "Local PDF Cleared"; Boolean)
        {
            Caption = 'Local PDF Cleared';
            DataClassification = SystemMetadata;
        }
        field(70519; "Archive File Name"; Text[250])
        {
            Caption = 'Archive File Name';
            DataClassification = CustomerContent;
        }
        field(70520; "Statement Start Date"; Date)
        {
            Caption = 'Statement Start Date';
            DataClassification = CustomerContent;
        }
        field(70521; "Statement End Date"; Date)
        {
            Caption = 'Statement End Date';
            DataClassification = CustomerContent;
        }
    }
}
