tableextension 70520 "GPI Sales Inv Line Visibility" extends "Sales Invoice Line"
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
