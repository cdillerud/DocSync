tableextension 70514 "GPI Purch Cr Memo Hdr Ext" extends "Purch. Cr. Memo Hdr."
{
    fields
    {
        field(70510; "GPI Purch Cr Memo Status"; Enum "GPI Delivery Status")
        {
            Caption = 'GPI Purchase Credit Memo Status';
            DataClassification = CustomerContent;
        }
        field(70511; "GPI Purch Cr Memo Recipient"; Text[2048])
        {
            Caption = 'GPI Purchase Credit Memo Recipient';
            DataClassification = EndUserIdentifiableInformation;
        }
        field(70512; "GPI Last Delivery Entry No."; Integer)
        {
            Caption = 'GPI Last Delivery Entry No.';
            DataClassification = SystemMetadata;
        }
        field(70513; "GPI Last Delivery Date/Time"; DateTime)
        {
            Caption = 'GPI Last Delivery Date/Time';
            DataClassification = SystemMetadata;
        }
        field(70514; "GPI Last Delivery Error"; Text[2048])
        {
            Caption = 'GPI Last Delivery Error';
            DataClassification = CustomerContent;
        }
        field(70515; "GPI Last Sender Email"; Text[250])
        {
            Caption = 'GPI Last Sender Email';
            DataClassification = EndUserIdentifiableInformation;
        }
    }
}
