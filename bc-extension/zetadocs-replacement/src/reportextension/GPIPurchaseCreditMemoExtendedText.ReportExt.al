reportextension 70547 "GPI Purch Cr Memo Ext Text" extends "GPI Purchase Credit Memo"
{
    dataset
    {
        add(PurchaseCreditMemoLine)
        {
            column(LineExtendedText; ExtendedTextMgt.GetItemExtendedText(PurchaseCreditMemoLine."No."))
            {
            }
        }
    }

    var
        ExtendedTextMgt: Codeunit "GPI Extended Text Mgt.";
}