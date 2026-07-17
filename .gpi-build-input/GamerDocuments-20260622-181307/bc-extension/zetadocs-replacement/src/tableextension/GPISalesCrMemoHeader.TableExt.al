tableextension 70513 "GPI Sales Cr Memo Header Ext" extends "Sales Cr.Memo Header"
{
    fields
    {
        field(70510; "GPI Credit Delivery Status"; Enum "GPI Delivery Status")
        {
            Caption = 'GPI Credit Memo Delivery Status';
            DataClassification = CustomerContent;
        }

        field(70511; "GPI Credit Recipient"; Text[2048])
        {
            Caption = 'GPI Credit Memo Recipient';
            DataClassification = EndUserIdentifiableInformation;
        }

        field(70512; "GPI Last Delivery Entry No."; Integer)
        {
            Caption = 'GPI Last Delivery Entry No.';
            DataClassification = SystemMetadata;
            TableRelation = "GPI Document Delivery Log"."Entry No.";
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

    keys
    {
        key(GPICreditDeliveryStatus; "GPI Credit Delivery Status")
        {
        }
    }
}
