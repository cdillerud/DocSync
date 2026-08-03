pageextension 70542 "GPI Purchase Order Visibility" extends "Purchase Order Subform"
{
    layout
    {
        addafter(Quantity)
        {
            field("GPI Document Visibility"; Rec."GPI Document Visibility")
            {
                ApplicationArea = All;
                ToolTip = 'Specifies which generated documents include this line.';
            }
        }
    }
}
