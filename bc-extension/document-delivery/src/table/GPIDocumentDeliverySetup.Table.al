table 70150000 "GPI Doc Delivery Setup"
{
    Caption = 'GPI Document Delivery Setup';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Primary Key"; Code[10])
        {
            Caption = 'Primary Key';
        }
        field(10; "Integration Enabled"; Boolean)
        {
            Caption = 'Integration Enabled';
            InitValue = false;
        }
        field(20; "Hub Base URL"; Text[250])
        {
            Caption = 'GPI Hub Base URL';
            ExtendedDatatype = URL;
        }
        field(30; "API Key"; Text[250])
        {
            Caption = 'API Key';
            ExtendedDatatype = Masked;
        }
        field(40; "Environment Name"; Text[100])
        {
            Caption = 'Environment Name';
        }
        field(50; "Company ID"; Text[100])
        {
            Caption = 'Company ID';
        }
        field(60; "Company Name"; Text[100])
        {
            Caption = 'Company Name';
        }
        field(70; "Log Successful Events"; Boolean)
        {
            Caption = 'Log Successful Events';
            InitValue = true;
        }
        field(80; "Last Test Status"; Text[250])
        {
            Caption = 'Last Test Status';
            Editable = false;
        }
        field(90; "Last Test At"; DateTime)
        {
            Caption = 'Last Test At';
            Editable = false;
        }
        field(100; "Last Event Sent At"; DateTime)
        {
            Caption = 'Last Event Sent At';
            Editable = false;
        }
        field(110; "Last Event Error"; Text[500])
        {
            Caption = 'Last Event Error';
            Editable = false;
        }
        field(120; "Document Link Template"; Text[500])
        {
            Caption = 'Document Link Template';
            ToolTip = 'Specifies an optional SharePoint/Zetadocs-style URL template to include in GPI Hub events. Supported tokens: {DocumentNo}, {RecordNo}, {FileName}, {CompanyName}, {EnvironmentName}.';
        }
        field(130; "Document Folder Template"; Text[250])
        {
            Caption = 'Document Folder Template';
            ToolTip = 'Specifies an optional logical folder path template to include in GPI Hub events. Supported tokens: {DocumentNo}, {RecordNo}, {FileName}, {CompanyName}, {EnvironmentName}.';
        }
        field(140; "Document Storage Provider"; Text[50])
        {
            Caption = 'Document Storage Provider';
            InitValue = 'SharePoint/Zetadocs';
            ToolTip = 'Specifies the external document storage label to include in event metadata.';
        }
        field(150; "Preview Document No."; Code[50])
        {
            Caption = 'Preview Document No.';
            InitValue = '296152';
            ToolTip = 'Specifies the sample document number used by the Preview Document Link action.';
        }
        field(160; "Preview File Name"; Text[250])
        {
            Caption = 'Preview File Name';
            InitValue = '296152.pdf';
            ToolTip = 'Specifies the sample file name used by the Preview Document Link action.';
        }
    }

    keys
    {
        key(PK; "Primary Key")
        {
            Clustered = true;
        }
    }
}
