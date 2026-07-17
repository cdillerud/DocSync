reportextension 70546 "GPI Prepay Ext Text" extends "GPI Prepayment Notice"
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