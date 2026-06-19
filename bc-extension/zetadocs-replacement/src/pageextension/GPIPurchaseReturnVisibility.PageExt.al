pageextension 70561 "GPI Purchase Return Visibility" extends "Purchase Return Order Subform"
{
    layout
    {
        addafter(Description)
        {
            field("GPI Document Visibility"; Rec."GPI Document Visibility")
            {
                ApplicationArea = All;
                ToolTip = 'Specifies whether the line appears on both return documents, only the vendor document, only the warehouse pick ticket, or neither document.';
            }
        }
    }
}
