reportextension 70559 "GPI Transfer Pick Ext Text" extends "GPI Transfer Pick List"
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