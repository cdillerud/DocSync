pageextension 70532 "GPI Purch Cr Memo List Ext" extends "Posted Purchase Credit Memos"
{
    actions
    {
        addlast(Processing)
        {
            group(GPIGamerDocuments)
            {
                Caption = 'Gamer Documents';
                Image = Documents;

                action(GPIPreviewPurchaseCreditMemo)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Purchase Credit Memo';
                    Image = View;
                    Promoted = true;
                    PromotedCategory = Process;

                    trigger OnAction()
                    var
                        PurchaseCreditMemoEmail: Codeunit "GPI Purchase Credit Memo Email";
                    begin
                        PurchaseCreditMemoEmail.PreviewPurchaseCreditMemo(Rec);
                    end;
                }

                action(GPIEmailPurchaseCreditMemo)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Purchase Credit Memo';
                    Image = SendMail;
                    Promoted = true;
                    PromotedCategory = Process;

                    trigger OnAction()
                    var
                        PurchaseCreditMemoEmail: Codeunit "GPI Purchase Credit Memo Email";
                    begin
                        PurchaseCreditMemoEmail.OpenPurchaseCreditMemoDraft(Rec);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIPurchaseCreditMemoDeliveryLog)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Delivery Log';
                    Image = Log;

                    trigger OnAction()
                    var
                        DeliveryLog: Record "GPI Document Delivery Log";
                    begin
                        DeliveryLog.SetRange("Source Table ID", Database::"Purch. Cr. Memo Hdr.");
                        DeliveryLog.SetRange("Source Document No.", Rec."No.");
                        Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                    end;
                }

                action(GPIPurchaseCreditMemoSentHistory)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Sent Email History';
                    Image = Email;

                    trigger OnAction()
                    var
                        Email: Codeunit Email;
                    begin
                        Email.OpenSentEmails(Database::"Purch. Cr. Memo Hdr.", Rec.SystemId);
                    end;
                }
            }
        }
    }
}
