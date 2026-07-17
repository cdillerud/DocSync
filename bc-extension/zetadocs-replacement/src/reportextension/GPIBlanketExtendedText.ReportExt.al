reportextension 70539 "GPI Blanket Ext Text" extends "GPI Blanket Sales Order"
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