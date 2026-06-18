pageextension 70529 "GPI Credit Memo List Ext" extends "Posted Sales Credit Memos"
{
    actions
    {
        addlast(Processing)
        {
            group(GPIGamerDocuments)
            {
                Caption = 'Gamer Documents';
                Image = Documents;

                action(GPIPreviewCreditMemo)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Credit Memo';
                    Image = View;
                    Promoted = true;
                    PromotedCategory = Process;

                    trigger OnAction()
                    var
                        CreditMemoEmail: Codeunit "GPI Sales Credit Memo Email";
                    begin
                        CreditMemoEmail.PreviewCreditMemo(Rec);
                    end;
                }

                action(GPIEmailCreditMemo)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Credit Memo';
                    Image = SendMail;
                    Promoted = true;
                    PromotedCategory = Process;

                    trigger OnAction()
                    var
                        CreditMemoEmail: Codeunit "GPI Sales Credit Memo Email";
                    begin
                        CreditMemoEmail.OpenCreditMemoDraft(Rec);
                        CurrPage.Update(false);
                    end;
                }

                action(GPICreditMemoDeliveryLog)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Delivery Log';
                    Image = Log;

                    trigger OnAction()
                    var
                        DeliveryLog: Record "GPI Document Delivery Log";
                    begin
                        DeliveryLog.SetRange("Source Table ID", Database::"Sales Cr.Memo Header");
                        DeliveryLog.SetRange("Source Document No.", Rec."No.");
                        Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                    end;
                }

                action(GPICreditMemoSentHistory)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Sent Email History';
                    Image = Email;

                    trigger OnAction()
                    var
                        Email: Codeunit Email;
                    begin
                        Email.OpenSentEmails(Database::"Sales Cr.Memo Header", Rec.SystemId);
                    end;
                }
            }
        }
    }
}
