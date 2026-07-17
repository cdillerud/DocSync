pageextension 70511 "GPI Posted Sales Invoices Ext" extends "Posted Sales Invoices"
{
    actions
    {
        addfirst(Processing)
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
            action(GPIOpenEndOfDayInvoiceBatch)
            {
                ApplicationArea = All;
                Caption = 'Gamer EOD Invoice Batch';
                Image = SendMail;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Opens the Gamer posted invoice queue filtered to invoices posted today with Amount not equal to zero, matching the end-of-day Zetadocs send procedure.';

                trigger OnAction()
                var
                    SalesInvoiceHeader: Record "Sales Invoice Header";
                begin
                    SalesInvoiceHeader.SetRange("Posting Date", Today);
                    SalesInvoiceHeader.SetFilter(Amount, '<>0');
                    Page.Run(Page::"GPI Posted Invoice Queue", SalesInvoiceHeader);
                end;
            }
        }
    }
}

