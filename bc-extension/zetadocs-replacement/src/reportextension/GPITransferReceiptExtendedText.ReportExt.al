reportextension 70562 "GPI Transfer Rcpt Ext Text" extends "GPI Transfer Receipt Notice"
{
    dataset
    {
        add(TransferLine)
        {
            column(LineExtendedText; ExtendedTextMgt.GetItemExtendedText(TransferLine."Item No."))
            {
            }
        }
    }

    var
        ExtendedTextMgt: Codeunit "GPI Extended Text Mgt.";
}