pageextension 70525 "GPI Vendor Card Docs Ext" extends "Vendor Card"
{
    actions
    {
        addlast(Processing)
        {
            group(GPIGamerDocuments)
            {
                Caption = 'Gamer Documents';
                Image = Documents;

                action(GPIVendorRoutingRules)
                {
                    ApplicationArea = All;
                    Caption = 'Gamer Document Routing Rules';
                    Image = Setup;
                    ToolTip = 'Shows Gamer document routing rules filtered to this vendor.';

                    trigger OnAction()
                    var
                        RoutingRule: Record "GPI Document Routing Rule";
                    begin
                        RoutingRule.SetRange("Vendor No.", Rec."No.");
                        Page.Run(Page::"GPI Document Routing Rules", RoutingRule);
                    end;
                }
            }
        }
    }
}