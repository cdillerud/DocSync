pageextension 70534 "GPI Customer List Statements" extends "Customer List"
{
    actions
    {
        addlast(Processing)
        {
            group(GPIStatementActions)
            {
                Caption = 'Gamer Statements';
                Image = Documents;

                action(GPIEmailCustomerStatements)
                {
                    ApplicationArea = All;
                    Caption = 'Email Customer Statements';
                    Image = SendMail;
                    Promoted = true;
                    PromotedCategory = Process;
                    ToolTip = 'Emails customer statements for the selected customers or current customer filter.';

                    trigger OnAction()
                    var
                        CustomerSelection: Record Customer;
                    begin
                        CurrPage.SetSelectionFilter(CustomerSelection);
                        Report.RunModal(
                            Report::"GPI Email Customer Statements",
                            true,
                            true,
                            CustomerSelection);
                        CurrPage.Update(false);
                    end;
                }

                action(GPIStatementRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Customer Statement Routing Rules';
                    Image = Setup;
                    ToolTip = 'Opens routing rules for customer statements.';

                    trigger OnAction()
                    var
                        RoutingRule: Record "GPI Document Routing Rule";
                    begin
                        RoutingRule.SetRange("Delivery Document Type", Enum::"GPI Delivery Document Type"::"Customer Statement");
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
            }
        }
    }
}
