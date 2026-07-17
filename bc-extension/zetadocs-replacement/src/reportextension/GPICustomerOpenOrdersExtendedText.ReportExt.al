reportextension 70543 "GPI Open Orders Ext Text" extends "GPI Customer Open Orders"
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