pageextension 70523 "GPI Customer Card Docs Ext" extends "Customer Card"
{
    actions
    {
        addlast(Processing)
        {
            group(GPIGamerDocuments)
            {
                Caption = 'Gamer Documents';
                Image = Documents;

                action(GPIPreviewCustomerStatement)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Preview Statement';
                    Image = View;
                    Promoted = true;
                    PromotedCategory = Process;
                    ToolTip = 'Creates and opens a customer statement PDF for the selected period.';

                    trigger OnAction()
                    var
                        StatementEmail: Codeunit "GPI Customer Statement Email";
                        StatementOptions: Page "GPI Statement Options";
                        StartDate: Date;
                        EndDate: Date;
                    begin
                        StatementEmail.GetDefaultDates(StartDate, EndDate);
                        StatementOptions.SetDates(StartDate, EndDate);
                        if StatementOptions.RunModal() <> Action::OK then
                            exit;
                        StatementOptions.GetDates(StartDate, EndDate);
                        StatementEmail.PreviewStatement(Rec, StartDate, EndDate);
                    end;
                }

                action(GPIEmailCustomerStatement)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Email Statement';
                    Image = SendMail;
                    Promoted = true;
                    PromotedCategory = Process;
                    ToolTip = 'Creates a customer statement PDF and opens the native Business Central email editor.';

                    trigger OnAction()
                    var
                        StatementEmail: Codeunit "GPI Customer Statement Email";
                        StatementOptions: Page "GPI Statement Options";
                        StartDate: Date;
                        EndDate: Date;
                    begin
                        StatementEmail.GetDefaultDates(StartDate, EndDate);
                        StatementOptions.SetDates(StartDate, EndDate);
                        if StatementOptions.RunModal() <> Action::OK then
                            exit;
                        StatementOptions.GetDates(StartDate, EndDate);
                        StatementEmail.OpenStatementDraft(Rec, StartDate, EndDate);
                        CurrPage.Update(false);
                    end;
                }

                action(GPICustomerStatementDeliveryLog)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Statement Delivery Log';
                    Image = Log;
                    ToolTip = 'Shows customer statement email, draft, failure, and SharePoint archive history.';

                    trigger OnAction()
                    var
                        DeliveryLog: Record "GPI Document Delivery Log";
                    begin
                        DeliveryLog.SetRange("Delivery Document Type", Enum::"GPI Delivery Document Type"::"Customer Statement");
                        DeliveryLog.SetRange("Source Table ID", Database::Customer);
                        DeliveryLog.SetRange("Source Document No.", Rec."No.");
                        Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                    end;
                }

                action(GPICustomerStatementSentHistory)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Sent Email History';
                    Image = Email;
                    ToolTip = 'Shows native Business Central sent emails related to this customer.';

                    trigger OnAction()
                    var
                        Email: Codeunit Email;
                    begin
                        Email.OpenSentEmails(Database::Customer, Rec.SystemId);
                    end;
                }

                action(GPICustomerStatementRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Statement Routing Rules';
                    Image = Setup;
                    ToolTip = 'Shows Customer Statement routing rules filtered to this customer.';

                    trigger OnAction()
                    var
                        RoutingRule: Record "GPI Document Routing Rule";
                    begin
                        RoutingRule.SetRange("Delivery Document Type", Enum::"GPI Delivery Document Type"::"Customer Statement");
                        RoutingRule.SetRange("Customer No.", Rec."No.");
                        Page.Run(Page::"GPI Document Routing Rules", RoutingRule);
                    end;
                }

                action(GPIConfigureStatementSender)
                {
                    ApplicationArea = All;
                    Caption = 'Configure Statement Sender';
                    Image = Setup;
                    ToolTip = 'Opens Email Scenario Setup so GPI Customer Statement can be assigned to the Accounting mailbox.';

                    trigger OnAction()
                    begin
                        Page.RunModal(Page::"Email Scenario Setup");
                    end;
                }

                action(GPICustomerRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'All Gamer Document Routing Rules';
                    Image = Setup;
                    ToolTip = 'Shows all Gamer document routing rules filtered to this customer.';

                    trigger OnAction()
                    var
                        RoutingRule: Record "GPI Document Routing Rule";
                    begin
                        RoutingRule.SetRange("Customer No.", Rec."No.");
                        Page.Run(Page::"GPI Document Routing Rules", RoutingRule);
                    end;
                }
            }
        }
    }
}
