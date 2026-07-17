reportextension 70555 "GPI Sales Invoice Ext Text" extends "GPI Sales Invoice"
{
    dataset
    {
        add(SalesInvoiceLine)
        {
            column(LineExtendedText; ExtendedTextMgt.GetItemExtendedText(SalesInvoiceLine."No."))
            {
            }
        }
    }

    var
        ExtendedTextMgt: Codeunit "GPI Extended Text Mgt.";
}