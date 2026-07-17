reportextension 70553 "GPI Purch Ret Pick Ext Text" extends "GPI Purchase Return Pick"
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