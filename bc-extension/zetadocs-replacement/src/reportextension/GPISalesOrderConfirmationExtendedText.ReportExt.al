reportextension 70556 "GPI SO Confirm Ext Text" extends "GPI Sales Order Confirmation"
{
    dataset
    {
        add(SalesLine)
        {
            column(LineExtendedText; ExtendedTextMgt.GetItemExtendedText(SalesLine."No."))
            {
            }
        }
    }

    var
        ExtendedTextMgt: Codeunit "GPI Extended Text Mgt.";
}