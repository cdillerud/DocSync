page 70513 "GPI Posted Invoice Queue"
{
    Caption = 'GPI Posted Sales Invoice Queue';
    PageType = List;
    SourceTable = "Sales Invoice Header";
    SourceTableView = sorting("Posting Date", "No.") order(descending);
    ApplicationArea = All;
    UsageCategory = Tasks;
    Editable = false;
    CardPageId = "Posted Sales Invoice";

    layout
    {
        area(Content)
        {
            repeater(Invoices)
            {
                field("Posting Date"; Rec."Posting Date")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the posting date of the invoice.';
                }

                field("No."; Rec."No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the posted sales invoice number.';
                }

                field("GPI Invoice Delivery Status"; Rec."GPI Invoice Delivery Status")
                {
                    ApplicationArea = All;
                    StyleExpr = StatusStyle;
                    ToolTip = 'Specifies whether the invoice is ready, missing a recipient, sent, or failed.';
                }

                field("Bill-to Customer No."; Rec."Bill-to Customer No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the customer that receives the invoice.';
                }

                field("Bill-to Name"; Rec."Bill-to Name")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the bill-to customer name.';
                }

                field("GPI Invoice Recipient"; Rec."GPI Invoice Recipient")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the resolved invoice recipient after Customer Card defaults and routing rules are applied.';
                }

                field("Order No."; Rec."Order No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the related sales order number.';
                }

                field("External Document No."; Rec."External Document No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the customer purchase order or external reference.';
                }

                field("Salesperson Code"; Rec."Salesperson Code")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the salesperson associated with the invoice.';
                }

                field("Location Code"; Rec."Location Code")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the location code associated with the invoice.';
                }

                field("Currency Code"; Rec."Currency Code")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the invoice currency.';
                }

                field("Amount Including VAT"; Rec."Amount Including VAT")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the total invoice amount including tax.';
                }

                field("GPI Last Sender Email"; Rec."GPI Last Sender Email")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the email account that most recently sent or attempted to send the invoice.';
                }

                field("GPI Last Delivery Date/Time"; Rec."GPI Last Delivery Date/Time")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies when the invoice was most recently sent or attempted.';
                }

                field("GPI Last Delivery Error"; Rec."GPI Last Delivery Error")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the most recent invoice delivery error.';
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(RefreshRecipients)
            {
                ApplicationArea = All;
                Caption = 'Refresh Recipients';
                Image = Refresh;
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Recalculates invoice recipients and queue readiness for the invoices in the current filtered view.';

                trigger OnAction()
                var
                    InvoiceBatchEmail: Codeunit "GPI Invoice Batch Email";
                    FilteredInvoices: Record "Sales Invoice Header";
                begin
                    FilteredInvoices.CopyFilters(Rec);
                    InvoiceBatchEmail.RefreshQueue(FilteredInvoices);
                    CurrPage.Update(false);
                end;
            }

            action(PreviewInvoice)
            {
                ApplicationArea = All;
                Caption = 'Preview Invoice';
                Image = View;
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Opens the selected invoice PDF using the invoice report configured in Report Selection - Sales.';

                trigger OnAction()
                var
                    InvoiceBatchEmail: Codeunit "GPI Invoice Batch Email";
                    SalesInvoiceHeader: Record "Sales Invoice Header";
                begin
                    SalesInvoiceHeader.Get(Rec."No.");
                    InvoiceBatchEmail.PreviewInvoice(SalesInvoiceHeader);
                end;
            }

            action(SendSelected)
            {
                ApplicationArea = All;
                Caption = 'Send Selected';
                Image = SendMail;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Sends the selected ready invoices through the GPI Invoice Batch email scenario.';

                trigger OnAction()
                var
                    InvoiceBatchEmail: Codeunit "GPI Invoice Batch Email";
                    SelectedInvoices: Record "Sales Invoice Header";
                begin
                    CurrPage.SetSelectionFilter(SelectedInvoices);
                    InvoiceBatchEmail.SendInvoices(SelectedInvoices);
                    CurrPage.Update(false);
                end;
            }

            action(SendAllFiltered)
            {
                ApplicationArea = All;
                Caption = 'Send All Filtered';
                Image = SendMail;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Sends every ready invoice included in the current filters. Missing-recipient and previously sent invoices are skipped.';

                trigger OnAction()
                var
                    InvoiceBatchEmail: Codeunit "GPI Invoice Batch Email";
                    FilteredInvoices: Record "Sales Invoice Header";
                begin
                    FilteredInvoices.CopyFilters(Rec);
                    InvoiceBatchEmail.SendInvoices(FilteredInvoices);
                    CurrPage.Update(false);
                end;
            }

            action(OpenPostedInvoice)
            {
                ApplicationArea = All;
                Caption = 'Open Posted Invoice';
                Image = Document;
                ToolTip = 'Opens the selected posted sales invoice.';

                trigger OnAction()
                var
                    SalesInvoiceHeader: Record "Sales Invoice Header";
                begin
                    SalesInvoiceHeader.Get(Rec."No.");
                    Page.Run(Page::"Posted Sales Invoice", SalesInvoiceHeader);
                end;
            }

            action(OpenDeliveryLog)
            {
                ApplicationArea = All;
                Caption = 'Delivery Log';
                Image = Log;
                ToolTip = 'Shows delivery history for the selected posted sales invoice.';

                trigger OnAction()
                var
                    DeliveryLog: Record "GPI Document Delivery Log";
                begin
                    DeliveryLog.SetRange("Source Table ID", Database::"Sales Invoice Header");
                    DeliveryLog.SetRange("Source Document No.", Rec."No.");
                    Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                end;
            }

            action(OpenRoutingRules)
            {
                ApplicationArea = All;
                Caption = 'Document Routing Rules';
                Image = Setup;
                RunObject = page "GPI Document Routing Rules";
                ToolTip = 'Opens the customer and document-specific invoice routing rules.';
            }

            action(ShowTodayUnsent)
            {
                ApplicationArea = All;
                Caption = 'Show Today Unsent';
                Image = FilterLines;
                ToolTip = 'Restores the default queue filters for today and excludes sent invoices.';

                trigger OnAction()
                begin
                    Rec.Reset();
                    Rec.SetRange("Posting Date", Today);
                    Rec.SetFilter("GPI Invoice Delivery Status", '<>%1', Rec."GPI Invoice Delivery Status"::Sent);
                    CurrPage.Update(false);
                end;
            }

            action(ShowAllInvoices)
            {
                ApplicationArea = All;
                Caption = 'Show All Invoices';
                Image = ClearFilter;
                ToolTip = 'Clears the default posting date and delivery status filters.';

                trigger OnAction()
                begin
                    Rec.Reset();
                    CurrPage.Update(false);
                end;
            }
        }
    }

    trigger OnOpenPage()
    var
        InvoiceBatchEmail: Codeunit "GPI Invoice Batch Email";
        FilteredInvoices: Record "Sales Invoice Header";
    begin
        if Rec.GetFilter("Posting Date") = '' then
            Rec.SetRange("Posting Date", Today);

        if Rec.GetFilter("GPI Invoice Delivery Status") = '' then
            Rec.SetFilter("GPI Invoice Delivery Status", '<>%1', Rec."GPI Invoice Delivery Status"::Sent);

        FilteredInvoices.CopyFilters(Rec);
        InvoiceBatchEmail.RefreshQueue(FilteredInvoices);
    end;

    trigger OnAfterGetRecord()
    begin
        case Rec."GPI Invoice Delivery Status" of
            Rec."GPI Invoice Delivery Status"::Sent:
                StatusStyle := 'Favorable';
            Rec."GPI Invoice Delivery Status"::Ready:
                StatusStyle := 'Ambiguous';
            Rec."GPI Invoice Delivery Status"::Failed,
            Rec."GPI Invoice Delivery Status"::"Missing Recipient":
                StatusStyle := 'Unfavorable';
            else
                StatusStyle := 'Standard';
        end;
    end;

    var
        StatusStyle: Text;
}
