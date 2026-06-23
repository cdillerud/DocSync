tableextension 70521 "GPI Posted Sales Credit Line" extends "Sales Cr.Memo Line"
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
