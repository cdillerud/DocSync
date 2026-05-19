pageextension 70150001 "GPI Posted Purch Inv Ext" extends "Posted Purchase Invoice"
{
    actions
    {
        addlast(Processing)
        {
            action(GPISendHubPurchInvTestEvent)
            {
                ApplicationArea = All;
                Caption = 'Send GPI Hub Test Event';
                Image = SendTo;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Sends a metadata-only test event for this posted purchase invoice to GPI Document Hub. This does not resend the invoice, replace document delivery, or change Zetadocs behavior.';

                trigger OnAction()
                var
                    Bridge: Codeunit "GPI Posted Purch Inv Bridge";
                    PurchInvHeader: Record "Purch. Inv. Header";
                begin
                    PurchInvHeader.Get(Rec."No.");

                    if Bridge.SendPostedPurchaseInvoiceTestEvent(PurchInvHeader) then
                        Message('GPI Hub test event sent for posted purchase invoice %1.', Rec."No.")
                    else
                        Message('GPI Hub test event was not sent successfully. Check GPI Document Delivery Log.');
                end;
            }

            action(GPISendHubPurchInvDocumentLinkEvent)
            {
                ApplicationArea = All;
                Caption = 'Send GPI Hub Document Link';
                Image = LinkWeb;
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Sends a separate external-document-link event for this posted purchase invoice to GPI Document Hub. This does not upload a PDF or resend the invoice.';

                trigger OnAction()
                var
                    Bridge: Codeunit "GPI Posted Purch Inv Bridge";
                    PurchInvHeader: Record "Purch. Inv. Header";
                begin
                    PurchInvHeader.Get(Rec."No.");

                    if Bridge.SendPostedPurchaseInvoiceDocumentLinkEvent(PurchInvHeader) then
                        Message('GPI Hub document link event sent for posted purchase invoice %1.', Rec."No.")
                    else
                        Message('GPI Hub document link event was not sent successfully. Check GPI Document Delivery Log.');
                end;
            }
        }
    }
}
