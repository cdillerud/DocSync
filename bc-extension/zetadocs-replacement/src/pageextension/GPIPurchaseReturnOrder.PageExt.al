pageextension 70560 "GPI Purchase Return Docs" extends "Purchase Return Order"
{
    actions
    {
        addlast(Processing)
        {
            group(GPIPurchaseReturnDocuments)
            {
                Caption = 'Gamer Documents';
                Image = Documents;

                action(GPIEmailPurchaseReturnOrder)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Purchase Return Order';
                    Image = Email;
                    Promoted = true;
                    PromotedCategory = Process;
                    PromotedIsBig = true;
                    ToolTip = 'Creates the Gamer Purchase Return Order PDF and opens an email from the current Business Central user.';

                    trigger OnAction()
                    var
                        PurchaseReturnEmail: Codeunit "GPI Purchase Return Email";
                        PurchaseHeader: Record "Purchase Header";
                    begin
                        CurrPage.SaveRecord();
                        CommitPageChanges();
                        PurchaseHeader.Get(Rec."Document Type", Rec."No.");
                        PurchaseReturnEmail.OpenVendorReturnDraft(PurchaseHeader);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIEmailPurchaseReturnPick)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Return Pick Ticket';
                    Image = Email;
                    Promoted = true;
                    PromotedCategory = Process;
                    PromotedIsBig = true;
                    ToolTip = 'Creates the Gamer Purchase Return Pick Ticket PDF and opens an email from the current Business Central user.';

                    trigger OnAction()
                    var
                        PurchaseReturnEmail: Codeunit "GPI Purchase Return Email";
                        PurchaseHeader: Record "Purchase Header";
                    begin
                        CurrPage.SaveRecord();
                        CommitPageChanges();
                        PurchaseHeader.Get(Rec."Document Type", Rec."No.");
                        PurchaseReturnEmail.OpenPickTicketDraft(PurchaseHeader);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIPreviewPurchaseReturnOrder)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Purchase Return Order';
                    Image = Print;
                    ToolTip = 'Previews the Gamer Purchase Return Order without creating an email or delivery record.';

                    trigger OnAction()
                    var
                        PurchaseReturnEmail: Codeunit "GPI Purchase Return Email";
                        PurchaseHeader: Record "Purchase Header";
                    begin
                        CurrPage.SaveRecord();
                        CommitPageChanges();
                        PurchaseHeader.Get(Rec."Document Type", Rec."No.");
                        PurchaseReturnEmail.PreviewVendorReturn(PurchaseHeader);
                    end;
                }

                action(GPIPreviewPurchaseReturnPick)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Return Pick Ticket';
                    Image = Print;
                    ToolTip = 'Previews the Gamer Purchase Return Pick Ticket without creating an email or delivery record.';

                    trigger OnAction()
                    var
                        PurchaseReturnEmail: Codeunit "GPI Purchase Return Email";
                        PurchaseHeader: Record "Purchase Header";
                    begin
                        CurrPage.SaveRecord();
                        CommitPageChanges();
                        PurchaseHeader.Get(Rec."Document Type", Rec."No.");
                        PurchaseReturnEmail.PreviewPickTicket(PurchaseHeader);
                    end;
                }

                action(GPIViewPurchaseReturnDeliveryLog)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Delivery Log';
                    Image = Log;
                    ToolTip = 'Shows Gamer document delivery records for this Purchase Return Order.';

                    trigger OnAction()
                    var
                        DeliveryLog: Record "GPI Document Delivery Log";
                    begin
                        DeliveryLog.SetRange("Source Table ID", Database::"Purchase Header");
                        DeliveryLog.SetRange("Source Document No.", Rec."No.");
                        Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                    end;
                }

                action(GPIViewPurchaseReturnRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Routing Rules';
                    Image = Setup;
                    RunObject = page "GPI Document Routing Rules";
                    ToolTip = 'Opens vendor, location, and document-specific email recipient rules.';
                }

                action(GPIViewPurchaseReturnSentEmails)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Sent Email History';
                    Image = Email;
                    ToolTip = 'Shows native Business Central sent emails related to this Purchase Return Order.';

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
