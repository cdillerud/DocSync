pageextension 70511 "GPI Posted Sales Invoices Ext" extends "Posted Sales Invoices"
{
    actions
    {
        addlast(Processing)
        {
            action(GPIOpenInvoiceQueue)
            {
                ApplicationArea = All;
                Caption = 'Gamer Invoice Delivery Queue';
                Image = SendMail;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                RunObject = page "GPI Posted Invoice Queue";
                ToolTip = 'Opens the Gamer filterable end-of-day posted sales invoice email queue.';
            }
        }
    }
}
