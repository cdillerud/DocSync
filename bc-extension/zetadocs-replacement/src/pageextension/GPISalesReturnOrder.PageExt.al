pageextension 70551 "GPI Sales Return Documents" extends "Sales Return Order"
{
    actions
    {
        addlast(Processing)
        {
            group(GPIReturnDocuments)
            {
                Caption = 'Gamer Documents';
                Image = Documents;

                action(GPIEmailReturnAuthorization)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Return Authorization';
                    Image = Email;
                    Promoted = true;
                    PromotedCategory = Process;
                    PromotedIsBig = true;
                    ToolTip = 'Creates the Gamer Sales Return Authorization PDF and opens an email from the current Business Central user.';

                    trigger OnAction()
                    var
                        SalesReturnEmail: Codeunit "GPI Sales Return Email";
                        SalesHeader: Record "Sales Header";
                    begin
                        CurrPage.SaveRecord();
                        Commit();
                        SalesHeader.Get(Rec."Document Type", Rec."No.");
                        SalesReturnEmail.OpenAuthorizationDraft(SalesHeader);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIEmailReturnWarehouseNotice)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Warehouse Notification';
                    Image = Email;
                    Promoted = true;
                    PromotedCategory = Process;
                    PromotedIsBig = true;
                    ToolTip = 'Creates the Gamer Sales Return Warehouse Notification PDF and opens an email from the current Business Central user.';

                    trigger OnAction()
                    var
                        SalesReturnEmail: Codeunit "GPI Sales Return Email";
                        SalesHeader: Record "Sales Header";
                    begin
                        CurrPage.SaveRecord();
                        Commit();
                        SalesHeader.Get(Rec."Document Type", Rec."No.");
                        SalesReturnEmail.OpenWarehouseNotificationDraft(SalesHeader);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIPreviewReturnAuthorization)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Return Authorization';
                    Image = Print;
                    ToolTip = 'Previews the Gamer Sales Return Authorization without creating an email or delivery record.';

                    trigger OnAction()
                    var
                        SalesReturnEmail: Codeunit "GPI Sales Return Email";
                        SalesHeader: Record "Sales Header";
                    begin
                        CurrPage.SaveRecord();
                        Commit();
                        SalesHeader.Get(Rec."Document Type", Rec."No.");
                        SalesReturnEmail.PreviewAuthorization(SalesHeader);
                    end;
                }

                action(GPIPreviewReturnWarehouseNotice)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Warehouse Notification';
                    Image = Print;
                    ToolTip = 'Previews the Gamer Sales Return Warehouse Notification without creating an email or delivery record.';

                    trigger OnAction()
                    var
                        SalesReturnEmail: Codeunit "GPI Sales Return Email";
                        SalesHeader: Record "Sales Header";
                    begin
                        CurrPage.SaveRecord();
                        Commit();
                        SalesHeader.Get(Rec."Document Type", Rec."No.");
                        SalesReturnEmail.PreviewWarehouseNotification(SalesHeader);
                    end;
                }

                action(GPIViewReturnDeliveryLog)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Delivery Log';
                    Image = Log;
                    ToolTip = 'Shows Gamer document delivery records for this Sales Return Order.';

                    trigger OnAction()
                    var
                        DeliveryLog: Record "GPI Document Delivery Log";
                    begin
                        DeliveryLog.SetRange("Source Table ID", Database::"Sales Header");
                        DeliveryLog.SetRange("Source Document No.", Rec."No.");
                        Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                    end;
                }

                action(GPIViewReturnRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Routing Rules';
                    Image = Setup;
                    RunObject = page "GPI Document Routing Rules";
                    ToolTip = 'Opens customer, location, and document-specific email recipient rules.';
                }

                action(GPIViewReturnSentEmails)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Sent Email History';
                    Image = Email;
                    ToolTip = 'Shows native Business Central sent emails related to this Sales Return Order.';

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
}
