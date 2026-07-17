pageextension 70536 "GPI Hide SO Incoming Docs" extends "Sales Order"
{
    layout
    {
        modify(IncomingDocAttachFactBox)
        {
            Visible = false;
        }
    }
}