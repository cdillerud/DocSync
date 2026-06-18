tableextension 70515 "GPI Purchase Header Ext" extends "Purchase Header"
{
    fields
    {
        field(70510; "GPI WH Receipt Date"; Date)
        {
            Caption = 'Warehouse Receipt Date';
            DataClassification = CustomerContent;
        }
    }
}
