tableextension 70522 "GPI Posted Purch Credit Line" extends "Purch. Cr. Memo Line"
{
    fields
    {
        field(70510; "GPI Document Visibility"; Enum "GPI Document Visibility")
        {
            Caption = 'Document Visibility';
            DataClassification = CustomerContent;
            Editable = false;
        }
    }
}
