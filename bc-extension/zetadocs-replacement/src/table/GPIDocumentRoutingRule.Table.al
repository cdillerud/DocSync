table 70512 "GPI Document Routing Rule"
{
    Caption = 'GPI Document Routing Rule';
    DataClassification = CustomerContent;
    DrillDownPageId = "GPI Document Routing Rules";
    LookupPageId = "GPI Document Routing Rules";

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
            DataClassification = SystemMetadata;
        }

        field(2; Enabled; Boolean)
        {
            Caption = 'Enabled';
            InitValue = true;
            DataClassification = CustomerContent;
        }

        field(3; Priority; Integer)
        {
            Caption = 'Priority';
            InitValue = 100;
            MinValue = 0;
            DataClassification = CustomerContent;
            ToolTip = 'Specifies the order in which matching rules are applied. Lower numbers are applied first.';
        }

        field(4; "Rule Name"; Text[100])
        {
            Caption = 'Rule Name';
            DataClassification = CustomerContent;
        }

        field(5; "Delivery Document Type"; Enum "GPI Delivery Document Type")
        {
            Caption = 'Document Type';
            DataClassification = CustomerContent;
        }

        field(6; "Customer No."; Code[20])
        {
            Caption = 'Customer No.';
            DataClassification = CustomerContent;
            TableRelation = Customer."No.";
        }

        field(7; "Vendor No."; Code[20])
        {
            Caption = 'Vendor No.';
            DataClassification = CustomerContent;
            TableRelation = Vendor."No.";
        }

        field(8; "Location Code"; Code[10])
        {
            Caption = 'Location Code';
            DataClassification = CustomerContent;
            TableRelation = Location.Code;
        }

        field(9; Action; Enum "GPI Routing Rule Action")
        {
            Caption = 'Recipient Action';
            DataClassification = CustomerContent;
            ToolTip = 'Specifies whether the rule adds recipients to the defaults or replaces all default recipients.';
        }

        field(10; "To Addresses"; Text[2048])
        {
            Caption = 'To Addresses';
            DataClassification = EndUserIdentifiableInformation;
            ExtendedDatatype = EMail;
        }

        field(11; "CC Addresses"; Text[2048])
        {
            Caption = 'CC Addresses';
            DataClassification = EndUserIdentifiableInformation;
            ExtendedDatatype = EMail;
        }

        field(12; "BCC Addresses"; Text[2048])
        {
            Caption = 'BCC Addresses';
            DataClassification = EndUserIdentifiableInformation;
            ExtendedDatatype = EMail;
        }

        field(13; "Effective Start Date"; Date)
        {
            Caption = 'Effective Start Date';
            DataClassification = CustomerContent;

            trigger OnValidate()
            begin
                ValidateDateRange();
            end;
        }

        field(14; "Effective End Date"; Date)
        {
            Caption = 'Effective End Date';
            DataClassification = CustomerContent;

            trigger OnValidate()
            begin
                ValidateDateRange();
            end;
        }

        field(15; Notes; Text[2048])
        {
            Caption = 'Notes';
            DataClassification = CustomerContent;
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }

        key(Match; Enabled, "Delivery Document Type", Priority, "Entry No.")
        {
        }
    }

    local procedure ValidateDateRange()
    begin
        if ("Effective Start Date" <> 0D) and
           ("Effective End Date" <> 0D) and
           ("Effective End Date" < "Effective Start Date")
        then
            Error('The effective end date cannot be before the effective start date.');
    end;
}
