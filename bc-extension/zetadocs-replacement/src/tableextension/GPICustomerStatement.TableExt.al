tableextension 70517 "GPI Customer Statement Ext" extends Customer
{
    fields
    {
        field(70510; "GPI Statement Status"; Enum "GPI Delivery Status")
        {
            Caption = 'GPI Statement Status';
            DataClassification = CustomerContent;
        }
        field(70511; "GPI Statement Recipient"; Text[2048])
        {
            Caption = 'GPI Statement Recipient';
            DataClassification = EndUserIdentifiableInformation;
        }
        field(70512; "GPI Last Statement Entry No."; Integer)
        {
            Caption = 'GPI Last Statement Entry No.';
            DataClassification = SystemMetadata;
        }
        field(70513; "GPI Last Statement Date/Time"; DateTime)
        {
            Caption = 'GPI Last Statement Date/Time';
            DataClassification = SystemMetadata;
        }
        field(70514; "GPI Last Statement Error"; Text[2048])
        {
            Caption = 'GPI Last Statement Error';
            DataClassification = CustomerContent;
        }
        field(70515; "GPI Last Statement Sender"; Text[250])
        {
            Caption = 'GPI Last Statement Sender';
            DataClassification = EndUserIdentifiableInformation;
        }
        field(70516; "GPI Last Statement Start Date"; Date)
        {
            Caption = 'GPI Last Statement Start Date';
            DataClassification = CustomerContent;
        }
        field(70517; "GPI Last Statement End Date"; Date)
        {
            Caption = 'GPI Last Statement End Date';
            DataClassification = CustomerContent;
        }
    }
}
