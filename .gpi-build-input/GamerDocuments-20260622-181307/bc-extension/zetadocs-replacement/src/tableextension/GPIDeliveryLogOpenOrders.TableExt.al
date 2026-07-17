tableextension 70580 "GPI Delivery Log Open Orders" extends "GPI Document Delivery Log"
{
    fields
    {
        field(70580; "Open Order As Of Date"; Date)
        {
            Caption = 'Open Order As Of Date';
            DataClassification = CustomerContent;
        }
        field(70581; "Open Order Count"; Integer)
        {
            Caption = 'Open Order Count';
            DataClassification = CustomerContent;
        }
        field(70582; "Open Order Line Count"; Integer)
        {
            Caption = 'Open Order Line Count';
            DataClassification = CustomerContent;
        }
        field(70583; "Included Order Nos."; Text[2048])
        {
            Caption = 'Included Order Nos.';
            DataClassification = CustomerContent;
        }
    }
}
