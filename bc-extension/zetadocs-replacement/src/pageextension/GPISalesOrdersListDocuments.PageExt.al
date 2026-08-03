pageextension 70524 "GPI Sales Orders List Docs" extends "Sales Orders"
{
    actions
    {
        addlast(Processing)
        {
            group(GPIGamerDocuments)
            {
                Caption = 'Gamer Documents';
                Image = Documents;

                action(GPIEmailOrderConfirmation)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Order Confirmation';
                    Image = Email;
                    ToolTip = 'Creates the Gamer-owned Order Confirmation PDF and opens an email for review.';

                    trigger OnAction()
                    var
                        SalesOrderEmail: Codeunit "GPI Sales Order Email";
                        SalesHeader: Record "Sales Header";
                    begin
                        SalesHeader.Get(Rec."Document Type", Rec."No.");
                        SalesOrderEmail.OpenSalesOrderConfirmationDraft(SalesHeader);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIPreviewOrderConfirmation)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Order Confirmation';
                    Image = Print;
                    ToolTip = 'Previews the Gamer-owned Order Confirmation without creating an email or delivery record.';

                    trigger OnAction()
                    var
                        SalesHeader: Record "Sales Header";
                    begin
                        SalesHeader.Get(Rec."Document Type", Rec."No.");
                        SalesHeader.SetRecFilter();
                        Report.RunModal(Report::"GPI Sales Order Confirmation", true, false, SalesHeader);
                    end;
                }

                action(GPIEmailPrepaymentNotice)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Prepayment Notice';
                    Image = Email;
                    ToolTip = 'Creates the Gamer-owned Prepayment Notice PDF and opens an email for review.';

                    trigger OnAction()
                    var
                        SalesOrderEmail: Codeunit "GPI Sales Order Email";
                        SalesHeader: Record "Sales Header";
                    begin
                        SalesHeader.Get(Rec."Document Type", Rec."No.");
                        SalesOrderEmail.OpenPrepaymentNoticeDraft(SalesHeader);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIPreviewPrepaymentNotice)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Prepayment Notice';
                    Image = Print;
                    ToolTip = 'Previews the Gamer-owned Prepayment Notice without creating an email or delivery record.';

                    trigger OnAction()
                    var
                        SalesHeader: Record "Sales Header";
                    begin
                        SalesHeader.Get(Rec."Document Type", Rec."No.");
                        SalesHeader.SetRecFilter();
                        Report.RunModal(Report::"GPI Prepayment Notice", true, false, SalesHeader);
                    end;
                }

                action(GPIEmailPickTicket)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Pick Ticket';
                    Image = Email;
                    ToolTip = 'Creates the Gamer-owned Pick Ticket PDF and opens an email for review.';

                    trigger OnAction()
                    var
                        SalesOrderEmail: Codeunit "GPI Sales Order Email";
                        SalesHeader: Record "Sales Header";
                    begin
                        SalesHeader.Get(Rec."Document Type", Rec."No.");
                        SalesOrderEmail.OpenPickTicketDraft(SalesHeader);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIPreviewPickTicket)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Pick Ticket';
                    Image = Print;
                    ToolTip = 'Previews the Gamer-owned Pick Ticket without creating an email or delivery record.';

                    trigger OnAction()
                    var
                        SalesHeader: Record "Sales Header";
                    begin
                        SalesHeader.Get(Rec."Document Type", Rec."No.");
                        SalesHeader.SetRecFilter();
                        Report.RunModal(Report::"GPI Pick Ticket", true, false, SalesHeader);
                    end;
                }

                action(GPIViewDeliveryLog)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Delivery Log';
                    Image = Log;
                    ToolTip = 'Shows Gamer document delivery records for the selected Sales Order.';

                    trigger OnAction()
                    var
                        DeliveryLog: Record "GPI Document Delivery Log";
                    begin
                        DeliveryLog.SetRange("Sales Order No.", Rec."No.");
                        Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                    end;
                }

                action(GPIViewRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Routing Rules';
                    Image = Setup;
                    RunObject = page "GPI Document Routing Rules";
                    ToolTip = 'Opens customer, vendor, location, and document-specific email recipient rules.';
                }

                action(GPIViewSentEmails)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Sent Email History';
                    Image = Email;
                    ToolTip = 'Shows native Business Central sent emails related to the selected Sales Order.';

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
