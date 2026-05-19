pageextension 70150002 "GPI Posted Sales Cr Memo Ext" extends "Posted Sales Credit Memo"
{
    actions
    {
        addlast(Processing)
        {
            action(GPISendHubSalesCrMemoTestEvent)
            {
                ApplicationArea = All;
                Caption = 'Send GPI Hub Test Event';
                Image = SendTo;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Sends a metadata-only test event for this posted sales credit memo to GPI Document Hub.';

                trigger OnAction()
                var
                    Bridge: Codeunit "GPI Sales Cr Memo Bridge";
                    SalesCrMemoHeader: Record "Sales Cr.Memo Header";
                begin
                    SalesCrMemoHeader.Get(Rec."No.");

                    if Bridge.SendPostedSalesCreditMemoTestEvent(SalesCrMemoHeader) then
                        Message('GPI Hub test event sent for posted sales credit memo %1.', Rec."No.")
                    else
                        Message('GPI Hub test event was not sent successfully. Check GPI Document Delivery Log.');
                end;
            }

            action(GPISendHubSalesCrMemoDocumentLinkEvent)
            {
                ApplicationArea = All;
                Caption = 'Send GPI Hub Document Link';
                Image = LinkWeb;
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Sends a separate external-document-link event for this posted sales credit memo to GPI Document Hub.';

                trigger OnAction()
                var
                    Bridge: Codeunit "GPI Sales Cr Memo Bridge";
                    SalesCrMemoHeader: Record "Sales Cr.Memo Header";
                begin
                    SalesCrMemoHeader.Get(Rec."No.");

                    if Bridge.SendPostedSalesCreditMemoDocumentLinkEvent(SalesCrMemoHeader) then
                        Message('GPI Hub document link event sent for posted sales credit memo %1.', Rec."No.")
                    else
                        Message('GPI Hub document link event was not sent successfully. Check GPI Document Delivery Log.');
                end;
            }
        }
    }
}
