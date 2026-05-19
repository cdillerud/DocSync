pageextension 70150003 "GPI Posted Purch Cr Memo Ext" extends "Posted Purchase Credit Memo"
{
    actions
    {
        addlast(Processing)
        {
            action(GPISendHubPurchCrMemoTestEvent)
            {
                ApplicationArea = All;
                Caption = 'Send GPI Hub Test Event';
                Image = SendTo;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Sends a metadata-only test event for this posted purchase credit memo to GPI Document Hub.';

                trigger OnAction()
                var
                    Bridge: Codeunit "GPI Posted Purch Cr Memo Bridge";
                    PurchCrMemoHeader: Record "Purch. Cr. Memo Hdr.";
                begin
                    PurchCrMemoHeader.Get(Rec."No.");

                    if Bridge.SendPostedPurchaseCreditMemoTestEvent(PurchCrMemoHeader) then
                        Message('GPI Hub test event sent for posted purchase credit memo %1.', Rec."No.")
                    else
                        Message('GPI Hub test event was not sent successfully. Check GPI Document Delivery Log.');
                end;
            }

            action(GPISendHubPurchCrMemoDocumentLinkEvent)
            {
                ApplicationArea = All;
                Caption = 'Send GPI Hub Document Link';
                Image = LinkWeb;
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Sends a separate external-document-link event for this posted purchase credit memo to GPI Document Hub.';

                trigger OnAction()
                var
                    Bridge: Codeunit "GPI Posted Purch Cr Memo Bridge";
                    PurchCrMemoHeader: Record "Purch. Cr. Memo Hdr.";
                begin
                    PurchCrMemoHeader.Get(Rec."No.");

                    if Bridge.SendPostedPurchaseCreditMemoDocumentLinkEvent(PurchCrMemoHeader) then
                        Message('GPI Hub document link event sent for posted purchase credit memo %1.', Rec."No.")
                    else
                        Message('GPI Hub document link event was not sent successfully. Check GPI Document Delivery Log.');
                end;
            }
        }
    }
}
