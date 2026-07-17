reportextension 70564 "GPI Receiving Ext Text" extends "GPI Warehouse Receiving Notice"
{
    dataset
    {
        add(PurchaseLine)
        {
            column(LineExtendedText; ExtendedTextMgt.GetItemExtendedText(PurchaseLine."No."))
            {
            }
        }
    }

    var
        ExtendedTextMgt: Codeunit "GPI Extended Text Mgt.";
}