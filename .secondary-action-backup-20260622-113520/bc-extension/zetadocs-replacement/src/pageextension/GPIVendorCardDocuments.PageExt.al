pageextension 70526 "GPI Vendor Card Docs Ext" extends "Vendor Card"
{
    actions
    {
        addfirst(Processing)
        {
            group(GPIGamerDocuments)
            {
                Caption = 'Gamer Documents';
                Image = Documents;

                action(GPIVendorRoutingRules)
                {

                    PromotedIsBig = true;

                    PromotedCategory = Process;

                    Promoted = true;
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

