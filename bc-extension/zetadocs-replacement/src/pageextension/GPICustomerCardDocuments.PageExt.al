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

                action(GPICustomerDeliveryLog)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Delivery Log';
                    Image = Log;
                    ToolTip = 'Shows Gamer document delivery records for this customer.';

                    trigger OnAction()
                    var
                        DeliveryLog: Record "GPI Document Delivery Log";
                    begin
                        DeliveryLog.SetRange("Customer No.", Rec."No.");
                        Page.Run(Page::"GPI Document Delivery Log", DeliveryLog);
                    end;
                }

                action(GPICustomerRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Routing Rules';
                    Image = Setup;
                    ToolTip = 'Shows Gamer document routing rules for this customer.';

                    trigger OnAction()
                    var
                        RoutingRule: Record "GPI Document Routing Rule";
                    begin
                        RoutingRule.SetRange("Customer No.", Rec."No.");
                        Page.Run(Page::"GPI Document Routing Rules", RoutingRule);
                    end;
                }

                action(GPICustomerSentEmails)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Sent Email History';
                    Image = Email;
                    ToolTip = 'Shows native Business Central sent emails related to this customer.';

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
