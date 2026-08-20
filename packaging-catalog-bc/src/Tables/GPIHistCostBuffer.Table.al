table 71100 "GPI Hist Cost Buf"
{
    Caption = 'Historical Landed Cost Buffer';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Item Ledger Entry No."; Integer)
        {
            Caption = 'Item Ledger Entry No.';
        }
        field(2; "Item No."; Code[20])
        {
            Caption = 'BC Item No.';
        }
        field(3; "Posting Date"; Date)
        {
            Caption = 'Latest Cost Posting Date';
        }
        field(4; "Quantity EA"; Decimal)
        {
            Caption = 'Quantity EA';
            DecimalPlaces = 0 : 5;
        }
        field(10; "Direct Actual Cost"; Decimal)
        {
            Caption = 'Direct Item Cost';
            AutoFormatType = 2;
        }
        field(11; Freight; Decimal)
        {
            Caption = 'Freight';
            AutoFormatType = 2;
        }
        field(12; Customs; Decimal)
        {
            Caption = 'Customs';
            AutoFormatType = 2;
        }
        field(13; Drayage; Decimal)
        {
            Caption = 'Drayage';
            AutoFormatType = 2;
        }
        field(14; "Other Charges"; Decimal)
        {
            Caption = 'Other Item Charges';
            AutoFormatType = 2;
        }
        field(15; "Total Charges"; Decimal)
        {
            Caption = 'Total Item Charges';
            AutoFormatType = 2;
        }
        field(16; "Total Actual Cost"; Decimal)
        {
            Caption = 'Historical Landed Total';
            AutoFormatType = 2;
        }
        field(20; "Direct Cost per EA"; Decimal)
        {
            Caption = 'Direct Cost per EA';
            AutoFormatType = 2;
        }
        field(21; "Charges per EA"; Decimal)
        {
            Caption = 'Charges per EA';
            AutoFormatType = 2;
        }
        field(22; "Landed Cost per EA"; Decimal)
        {
            Caption = 'Historical Landed per EA';
            AutoFormatType = 2;
        }
        field(23; "M Qty. per UOM"; Decimal)
        {
            Caption = 'EA per M';
            DecimalPlaces = 0 : 5;
        }
        field(24; "Landed Cost per M"; Decimal)
        {
            Caption = 'Historical Landed per M';
            AutoFormatType = 2;
        }
        field(30; "Charge Codes"; Text[250])
        {
            Caption = 'Posted Item Charge Codes';
        }
    }

    keys
    {
        key(PK; "Item Ledger Entry No.")
        {
            Clustered = true;
        }
        key(DateKey; "Posting Date", "Item Ledger Entry No.")
        {
        }
    }
}
