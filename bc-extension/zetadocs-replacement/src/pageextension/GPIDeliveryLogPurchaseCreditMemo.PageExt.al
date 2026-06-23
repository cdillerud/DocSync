pageextension 70533 "GPI Delivery Log Purch Cr Memo" extends "GPI Document Delivery Log"
{
    actions
    {
        addafter(OpenSourceDocument)
        {
            action(GPIOpenPostedPurchaseCreditMemo)
            {
                ApplicationArea = All;
                Caption = 'Open Posted Purchase Credit Memo';
                Image = Document;
                Visible = IsPurchaseCreditMemo;
                ToolTip = 'Opens the posted purchase credit memo related to this delivery entry.';

                trigger OnAction()
                var
                    PurchaseCreditMemoHeader: Record "Purch. Cr. Memo Hdr.";
                begin
                    if not PurchaseCreditMemoHeader.Get(Rec."Source Document No.") then
                        Error('Posted Purchase Credit Memo %1 could not be found.', Rec."Source Document No.");

                    Page.Run(Page::"Posted Purchase Credit Memo", PurchaseCreditMemoHeader);
                end;
            }
        }
    }

    trigger OnAfterGetRecord()
    begin
        IsPurchaseCreditMemo := Rec."Delivery Document Type" = Rec."Delivery Document Type"::"Purchase Credit Memo";
    end;

    var
        IsPurchaseCreditMemo: Boolean;
}
