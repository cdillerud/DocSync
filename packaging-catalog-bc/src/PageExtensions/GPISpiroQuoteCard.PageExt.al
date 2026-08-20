pageextension 71104 "GPI Spiro Quote Card" extends "GPI Pack Quote Card"
{
    layout
    {
        addafter(General)
        {
            group(SpiroCRMContext)
            {
                Caption = 'Spiro CRM Context';

                field("GPI Spiro Company ID"; Rec."GPI Spiro Company ID")
                {
                    ApplicationArea = All;
                    Editable = false;
                    ToolTip = 'Shows the Spiro company mapped to this Business Central customer.';
                }
                field("GPI Spiro Company Name"; Rec."GPI Spiro Company Name")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Opportunity ID"; Rec."GPI Spiro Opportunity ID")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Opp. Name"; Rec."GPI Spiro Opp. Name")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Contact ID"; Rec."GPI Spiro Contact ID")
                {
                    ApplicationArea = All;
                    Editable = false;
                    Visible = false;
                }
                field("GPI Spiro Contact Name"; Rec."GPI Spiro Contact Name")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Stage"; Rec."GPI Spiro Stage")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Owner"; Rec."GPI Spiro Owner")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Synced At"; Rec."GPI Spiro Synced At")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Synced By"; Rec."GPI Spiro Synced By")
                {
                    ApplicationArea = All;
                    Editable = false;
                    Visible = false;
                }
            }
        }
    }

    actions
    {
        addlast(Processing)
        {
            action(OpenSpiroOpportunity)
            {
                ApplicationArea = All;
                Caption = 'Open Spiro Opportunity';
                Image = LinkWeb;
                Enabled = Rec."GPI Spiro Opp. URL" <> '';
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Opens the linked Spiro opportunity in the browser.';

                trigger OnAction()
                begin
                    if Rec."GPI Spiro Opp. URL" = '' then
                        Error('No Spiro opportunity URL is linked to this packaging quote.');
                    Hyperlink(Rec."GPI Spiro Opp. URL");
                end;
            }
            action(OpenSpiroCustomerMap)
            {
                ApplicationArea = All;
                Caption = 'Spiro Customer Mapping';
                Image = Customer;
                RunObject = page "GPI Spiro Cust Maps";
                RunPageLink = "BC Customer No." = field("Customer No.");
            }
        }
    }
}
