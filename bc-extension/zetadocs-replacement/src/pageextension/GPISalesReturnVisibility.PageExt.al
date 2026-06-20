pageextension 70552 "GPI Sales Return Visibility" extends "Sales Return Order Subform"
{
    layout
    {
        addafter(Description)
        {
            field("GPI Document Visibility"; Rec."GPI Document Visibility")
            {
                ApplicationArea = All;
                ToolTip = 'Specifies whether the line appears on both return documents, only the customer authorization, only the warehouse notification, or neither document.';
            }
        }
    }
}
