pageextension 70570 "GPI Transfer Documents" extends "Transfer Order"
{
    actions
    {
        addlast(Processing)
        {
            group(GPITransferDocuments)
            {
                Caption = 'Gamer Documents';
                Image = Documents;

                action(GPIEmailTransferPickList)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Transfer Pick List';
                    Image = Email;
                    Promoted = true;
                    PromotedCategory = Process;
                    PromotedIsBig = true;
                    ToolTip = 'Creates the Gamer Transfer Pick List PDF and opens an email from the current Business Central user.';

                    trigger OnAction()
                    var
                        TransferEmail: Codeunit "GPI Transfer Email";
                        TransferHeader: Record "Transfer Header";
                    begin
                        CurrPage.SaveRecord();
                        CommitPageChanges();
                        TransferHeader.Get(Rec."No.");
                        TransferEmail.OpenPickListDraft(TransferHeader);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIEmailTransferReceiptNotice)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Receipt Notification';
                    Image = Email;
                    Promoted = true;
                    PromotedCategory = Process;
                    PromotedIsBig = true;
                    ToolTip = 'Creates the Gamer Transfer Receipt Notification PDF and opens an email from the current Business Central user.';

                    trigger OnAction()
                    var
                        TransferEmail: Codeunit "GPI Transfer Email";
                        TransferHeader: Record "Transfer Header";
                    begin
                        CurrPage.SaveRecord();
                        CommitPageChanges();
                        TransferHeader.Get(Rec."No.");
                        TransferEmail.OpenReceiptNoticeDraft(TransferHeader);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIPreviewTransferPickList)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Transfer Pick List';
                    Image = Print;
                    ToolTip = 'Previews the Gamer Transfer Pick List without creating an email or delivery record.';

                    trigger OnAction()
                    var
                        TransferEmail: Codeunit "GPI Transfer Email";
                        TransferHeader: Record "Transfer Header";
                    begin
                        CurrPage.SaveRecord();
                        CommitPageChanges();
                        TransferHeader.Get(Rec."No.");
                        TransferEmail.PreviewPickList(TransferHeader);
                    end;
                }

                action(GPIPreviewTransferReceiptNotice)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Receipt Notification';
                    Image = Print;
                    ToolTip = 'Previews the Gamer Transfer Receipt Notification without creating an email or delivery record.';

                    trigger OnAction()
                    var
                        TransferEmail: Codeunit "GPI Transfer Email";
                        TransferHeader: Record "Transfer Header";
                    begin
                        CurrPage.SaveRecord();
                        CommitPageChanges();
                        TransferHeader.Get(Rec."No.");
                        TransferEmail.PreviewReceiptNotice(TransferHeader);
                    end;
                }

                action(GPIViewTransferDeliveryLog)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Delivery Log';
                    Image = Log;
                    ToolTip = 'Shows Gamer document delivery records for this Transfer Order.';

                    trigger OnAction()
                    var
                        DeliveryLog: Record "GPI Document Delivery Log";
                    begin
                        DeliveryLog.SetRange("Source Table ID", Database::"Transfer Header");
                        DeliveryLog.SetRange("Source Document No.", Rec."No.");
                        Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                    end;
                }

                action(GPIViewTransferRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Routing Rules';
                    Image = Setup;
                    RunObject = page "GPI Document Routing Rules";
                    ToolTip = 'Opens location and transfer-document-specific email recipient rules.';
                }

                action(GPIViewTransferSentEmails)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Sent Email History';
                    Image = Email;
                    ToolTip = 'Shows native Business Central sent emails related to this Transfer Order.';

                    trigger OnAction()
                    var
                        Email: Codeunit Email;
                    begin
                        Email.OpenSentEmails(Rec);
                    end;
                }
            }
        }
    }

    local procedure CommitPageChanges()
    var
        DeliveryTransportMgt: Codeunit "GPI Delivery Transport Mgt.";
    begin
        DeliveryTransportMgt.CommitChanges();
    end;
}
