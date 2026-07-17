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
                ToolTip = 'Opens the Gamer posted invoice queue filtered by selected Posting Date range and Amount not equal to zero.';

                trigger OnAction()
                var
                    SalesInvoiceHeader: Record "Sales Invoice Header";
                    EODOptions: Page "GPI EOD Invoice Batch Options";
                    PostingDateFrom: Date;
                    PostingDateTo: Date;
                begin
                    EODOptions.SetDefaultPostingDate(WorkDate());
                    if EODOptions.RunModal() <> Action::OK then
                        exit;

                    EODOptions.GetPostingDateFilter(PostingDateFrom, PostingDateTo);
                    if (PostingDateFrom = 0D) and (PostingDateTo = 0D) then
                        Error('Enter at least one Posting Date filter value.');

                    if (PostingDateFrom <> 0D) and (PostingDateTo <> 0D) and (PostingDateTo < PostingDateFrom) then
                        Error('Posting Date To cannot be before Posting Date From.');

                    if (PostingDateFrom <> 0D) and (PostingDateTo <> 0D) then
                        SalesInvoiceHeader.SetRange("Posting Date", PostingDateFrom, PostingDateTo)
                    else
                        if PostingDateFrom <> 0D then
                            SalesInvoiceHeader.SetFilter("Posting Date", '%1..', PostingDateFrom)
                        else
                            SalesInvoiceHeader.SetFilter("Posting Date", '..%1', PostingDateTo);

                    SalesInvoiceHeader.SetFilter(Amount, '<>0');
                    Page.Run(Page::"GPI Posted Invoice Queue", SalesInvoiceHeader);
                end;
            }
        }
    }
}

