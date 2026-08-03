pageextension 70541 "GPI Blanket Visibility" extends "Blanket Sales Order Subform"
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
