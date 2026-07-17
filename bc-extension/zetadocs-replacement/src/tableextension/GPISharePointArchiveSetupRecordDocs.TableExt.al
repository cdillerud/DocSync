tableextension 70620 "GPI SP Setup Record Docs" extends "GPI SharePoint Archive Setup"
{
    fields
    {
        field(70620; "Record Documents Folder"; Text[100])
        {
            Caption = 'Record Documents Folder';
            DataClassification = OrganizationIdentifiableInformation;
        }
        field(70621; "Maximum Upload Size MB"; Integer)
        {
            Caption = 'Maximum Upload Size (MB)';
            MinValue = 1;
            MaxValue = 100;
            DataClassification = SystemMetadata;
        }
        field(70622; "Blocked Upload Extensions"; Text[250])
        {
            Caption = 'Blocked Upload Extensions';
            DataClassification = SystemMetadata;
        }
    }
}
