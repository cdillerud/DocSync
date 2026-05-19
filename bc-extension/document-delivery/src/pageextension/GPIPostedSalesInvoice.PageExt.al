pageextension 70150000 "GPI Posted Sales Inv Ext" extends "Posted Sales Invoice"
{
    actions
    {
        addlast(Processing)
        {
            action(GPISendHubTestEvent)
            {
                ApplicationArea = All;
                Caption = 'Send GPI Hub Test Event';
                Image = SendTo;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Sends a metadata-only test event for this posted sales invoice to GPI Document Hub. This does not resend the invoice, replace document delivery, or change Zetadocs behavior.';

                trigger OnAction()
                var
                    Bridge: Codeunit "GPI Posted Sales Inv Bridge";
                    SalesInvoiceHeader: Record "Sales Invoice Header";
                begin
                    SalesInvoiceHeader.Get(Rec."No.");

                    if Bridge.SendPostedSalesInvoiceTestEvent(SalesInvoiceHeader) then
                        Message('GPI Hub test event sent for posted sales invoice %1.', Rec."No.")
                    else
                        Message('GPI Hub test event was not sent successfully. Check GPI Document Delivery Log.');
                end;
            }
        }
    }
}
