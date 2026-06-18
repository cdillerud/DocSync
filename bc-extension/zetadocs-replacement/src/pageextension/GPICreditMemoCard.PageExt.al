pageextension 70528 "GPI Credit Memo Card Ext" extends "Posted Sales Credit Memo"
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

                action(GPICreditMemoRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Routing Rules';
                    Image = Setup;

                    trigger OnAction()
                    var
                        RoutingRule: Record "GPI Document Routing Rule";
                    begin
                        RoutingRule.SetRange("Delivery Document Type", Enum::"GPI Delivery Document Type"::"Credit Memo");
                        RoutingRule.SetRange("Customer No.", Rec."Bill-to Customer No.");
                        Page.Run(Page::"GPI Document Routing Rules", RoutingRule);
                    end;
                }

                action(GPIConfigureCreditMemoSender)
                {
                    ApplicationArea = All;
                    Caption = 'Configure Accounting Sender';
                    Image = Setup;

                    trigger OnAction()
                    begin
                        Page.RunModal(Page::"Email Scenario Setup");
                    end;
                }
            }
        }
    }
}
