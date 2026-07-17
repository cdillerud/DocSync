reportextension 70554 "GPI Sales Cr Memo Ext Text" extends "GPI Sales Credit Memo"
{
    dataset
    {
        add(SalesCreditMemoLine)
        {
            column(LineExtendedText; ExtendedTextMgt.GetItemExtendedText(SalesCreditMemoLine."No."))
            {
            }
        }
    }

    var
        ExtendedTextMgt: Codeunit "GPI Extended Text Mgt.";
}