pageextension 70540 "GPI Sales Order Line Vis." extends "Sales Order Subform"
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
