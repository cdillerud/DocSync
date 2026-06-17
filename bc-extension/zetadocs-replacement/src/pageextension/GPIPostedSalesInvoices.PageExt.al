pageextension 70511 "GPI Posted Sales Invoices Ext" extends "Posted Sales Invoices"
{
    actions
    {
        addlast(Processing)
        {
            action(GPIOpenInvoiceQueue)
            {
                ApplicationArea = All;
                Caption = 'GPI Invoice Delivery Queue';
                Image = SendMail;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                RunObject = page "GPI Posted Invoice Queue";
                ToolTip = 'Opens the filterable end-of-day posted sales invoice email queue.';
            }
        }
    }
}
