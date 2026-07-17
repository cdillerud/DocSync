reportextension 70563 "GPI Warehouse PO Ext Text" extends "GPI Warehouse Purchase Order"
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