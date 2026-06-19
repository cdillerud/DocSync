pageextension 70571 "GPI Transfer Visibility" extends "Transfer Order Subform"
{
    layout
    {
        addafter(Description)
        {
            field("GPI Transfer Visibility"; Rec."GPI Transfer Visibility")
            {
                ApplicationArea = All;
                ToolTip = 'Specifies whether the line appears on both transfer documents, only the pick list, only the receipt notification, or neither document.';
            }
        }
    }
}
