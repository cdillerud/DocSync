pageextension 70537 "GPI Hide PO Incoming Docs" extends "Purchase Order"
{
    layout
    {
        modify(IncomingDocAttachFactBox)
        {
            Visible = false;
        }
    }
}