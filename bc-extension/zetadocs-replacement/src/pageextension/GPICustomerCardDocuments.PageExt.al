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

                action(GPICustomerRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Routing Rules';
                    Image = Setup;
                    ToolTip = 'Shows Gamer document routing rules filtered to this customer.';

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