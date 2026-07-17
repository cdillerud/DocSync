reportextension 70548 "GPI Purch Return Ext Text" extends "GPI Purchase Return Order"
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