table 70510 "GPI Document Delivery Log"
{
    Caption = 'GPI Document Delivery Log';
    DataClassification = CustomerContent;
    DrillDownPageId = "GPI Document Delivery Log";
    LookupPageId = "GPI Document Delivery Log";

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
            DataClassification = SystemMetadata;
        }

        field(2; "Delivery Document Type"; Enum "GPI Delivery Document Type")
        {
            Caption = 'Document Type';
            DataClassification = CustomerContent;
        }

        field(3; Status; Enum "GPI Delivery Status")
        {
            Caption = 'Status';
            DataClassification = CustomerContent;
        }

        field(4; "Sales Order No."; Code[20])
        {
            Caption = 'Sales Order No.';
            DataClassification = CustomerContent;
            TableRelation = "Sales Header"."No." where("Document Type" = const(Order));
        }

        field(5; "Sales Order SystemId"; Guid)
        {
            Caption = 'Sales Order System ID';
            DataClassification = SystemMetadata;
        }

        field(6; "Customer No."; Code[20])
        {
            Caption = 'Customer No.';
            DataClassification = CustomerContent;
            TableRelation = Customer."No.";
        }

        field(7; "Location Code"; Code[10])
        {
            Caption = 'Location Code';
            DataClassification = CustomerContent;
            TableRelation = Location.Code;
        }

        field(8; "Report ID"; Integer)
        {
            Caption = 'Report ID';
            DataClassification = SystemMetadata;
        }

        field(9; "Attachment Filename"; Text[250])
        {
            Caption = 'Attachment Filename';
            DataClassification = CustomerContent;
        }

        field(10; "Document Content"; Blob)
        {
            Caption = 'Document Content';
            DataClassification = CustomerContent;
        }

        field(11; "To Recipients"; Text[2048])
        {
            Caption = 'To';
            DataClassification = EndUserIdentifiableInformation;
        }

        field(12; "CC Recipients"; Text[2048])
        {
            Caption = 'CC';
            DataClassification = EndUserIdentifiableInformation;
        }

        field(13; Subject; Text[2048])
        {
            Caption = 'Subject';
            DataClassification = CustomerContent;
        }

        field(14; "Email Message ID"; Guid)
        {
            Caption = 'Email Message ID';
            DataClassification = SystemMetadata;
        }

        field(15; "External Delivery ID"; Text[2048])
        {
            Caption = 'External Delivery ID';
            DataClassification = SystemMetadata;
        }

        field(16; "Created Date/Time"; DateTime)
        {
            Caption = 'Created Date/Time';
            DataClassification = SystemMetadata;
        }

        field(17; "Created By"; Text[100])
        {
            Caption = 'Created By';
            DataClassification = EndUserIdentifiableInformation;
        }

        field(18; "Completed Date/Time"; DateTime)
        {
            Caption = 'Completed Date/Time';
            DataClassification = SystemMetadata;
        }

        field(19; "Completed By"; Text[100])
        {
            Caption = 'Completed By';
            DataClassification = EndUserIdentifiableInformation;
        }

        field(20; "Error Message"; Text[2048])
        {
            Caption = 'Error Message';
            DataClassification = CustomerContent;
        }

        field(21; "SharePoint URL"; Text[2048])
        {
            Caption = 'SharePoint URL';
            DataClassification = OrganizationIdentifiableInformation;
            ExtendedDatatype = URL;
        }

        field(22; "Source Table ID"; Integer)
        {
            Caption = 'Source Table ID';
            DataClassification = SystemMetadata;
        }

        field(23; "Source SystemId"; Guid)
        {
            Caption = 'Source System ID';
            DataClassification = SystemMetadata;
        }

        field(24; "Source Document Type"; Text[50])
        {
            Caption = 'Source Document Type';
            DataClassification = CustomerContent;
        }

        field(25; "Source Document No."; Code[20])
        {
            Caption = 'Source Document No.';
            DataClassification = CustomerContent;
        }

        field(26; "Source Party Type"; Text[20])
        {
            Caption = 'Source Party Type';
            DataClassification = CustomerContent;
        }

        field(27; "Source Party No."; Code[20])
        {
            Caption = 'Source Party No.';
            DataClassification = CustomerContent;
        }

        field(28; "Sender User"; Text[100])
        {
            Caption = 'Sender User';
            DataClassification = EndUserIdentifiableInformation;
        }

        field(29; "Sender Email Address"; Text[250])
        {
            Caption = 'Sender Email Address';
            DataClassification = EndUserIdentifiableInformation;
        }

        field(30; "Sender Policy"; Text[50])
        {
            Caption = 'Sender Policy';
            DataClassification = CustomerContent;
        }

        field(31; "Routing Rule Entry Nos."; Text[250])
        {
            Caption = 'Routing Rule Entry Nos.';
            DataClassification = SystemMetadata;
        }

        field(32; "BCC Recipients"; Text[2048])
        {
            Caption = 'BCC';
            DataClassification = EndUserIdentifiableInformation;
        }

        field(33; "Sender Account Name"; Text[250])
        {
            Caption = 'Sender Account Name';
            DataClassification = SystemMetadata;
        }

        field(34; "Sender Connector"; Text[100])
        {
            Caption = 'Sender Connector';
            DataClassification = SystemMetadata;
        }

        field(35; "Sender Account ID"; Guid)
        {
            Caption = 'Sender Account ID';
            DataClassification = SystemMetadata;
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }

        key(SalesOrder; "Sales Order No.", "Created Date/Time")
        {
        }

        key(Source; "Source Table ID", "Source Document No.", "Created Date/Time")
        {
        }

        key(Status; Status, "Created Date/Time")
        {
        }
    }
}
