tableextension 70510 "GPI Sales Invoice Header Ext" extends "Sales Invoice Header"
{
    fields
    {
        field(70510; "GPI Invoice Delivery Status"; Enum "GPI Delivery Status")
        {
            Caption = 'GPI Invoice Delivery Status';
            DataClassification = CustomerContent;
        }

        field(70511; "GPI Invoice Recipient"; Text[2048])
        {
            Caption = 'GPI Invoice Recipient';
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
        key(GPIDeliveryStatus; "GPI Invoice Delivery Status")
        {
        }
    }
}
