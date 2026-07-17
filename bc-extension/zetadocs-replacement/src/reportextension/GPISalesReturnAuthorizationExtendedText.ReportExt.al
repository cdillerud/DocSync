reportextension 70557 "GPI Sales Return Ext Text" extends "GPI Sales Return Auth."
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