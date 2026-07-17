reportextension 70544 "GPI Drop Ship PO Ext Text" extends "GPI Drop Ship Purchase Order"
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