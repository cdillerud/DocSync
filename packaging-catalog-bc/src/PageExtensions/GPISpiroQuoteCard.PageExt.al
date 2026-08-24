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
                }                field("GPI Spiro Assigned ISR"; Rec."GPI Spiro Assigned ISR")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Probability"; Rec."GPI Spiro Probability")
                {
                    ApplicationArea = All;
                    Editable = false;
                    Caption = 'Spiro Probability %';
                }
                field("GPI Spiro Est. Annual Volume"; Rec."GPI Spiro Est. Annual Volume")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Close Date"; Rec."GPI Spiro Close Date")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Rating"; Rec."GPI Spiro Rating")
                {
                    ApplicationArea = All;
                    Editable = false;
                }                field("GPI Spiro Push Status"; Rec."GPI Spiro Push Status")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Last Pushed At"; Rec."GPI Spiro Last Pushed At")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("GPI Spiro Push Message"; Rec."GPI Spiro Push Message")
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
            action(SelectSpiroOpportunity)
            {
                ApplicationArea = All;
                Caption = 'Select Spiro Opportunity';
                Image = SelectEntries;
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Selects a cached Spiro opportunity for the quote customer. The cache is populated by the external Spiro integration process.';

                trigger OnAction()
                var
                    SpiroLinkMgt: Codeunit "GPI Spiro Link Mgt";
                begin
                    SpiroLinkMgt.SelectOpportunity(Rec);
                    CurrPage.Update(false);
                end;
            }
            action(PushQuoteLinkToSpiro)
            {
                ApplicationArea = All;
                Caption = 'Push Quote Link to Spiro';
                Image = SendTo;
                Enabled = Rec."GPI Spiro Opportunity ID" <> '';
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Queues this Business Central packaging quote link for the external Spiro integration worker. Spiro credentials remain outside Business Central.';

                trigger OnAction()
                var
                    SpiroPushMgt: Codeunit "GPI Spiro Push Mgt";
                begin
                    SpiroPushMgt.QueueQuoteLink(Rec);
                    CurrPage.Update(false);
                    Message('Spiro quote-link writeback request queued.');
                end;
            }
            action(RefreshSpiroContext)
            {
                ApplicationArea = All;
                Caption = 'Refresh Spiro Context';
                Image = Refresh;
                Enabled = Rec."GPI Spiro Opportunity ID" <> '';
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Refreshes the linked Spiro opportunity snapshot on this quote from the latest Business Central Spiro opportunity cache. No Spiro write is performed.';

                trigger OnAction()
                var
                    SpiroLinkMgt: Codeunit "GPI Spiro Link Mgt";
                begin
                    SpiroLinkMgt.RefreshLinkedOpportunity(Rec);
                    CurrPage.Update(false);
                    Message('Spiro context refreshed from the local opportunity cache.');
                end;
            }
            action(UnlinkSpiroOpportunity)
            {
                ApplicationArea = All;
                Caption = 'Unlink Spiro Opportunity';
                Image = RemoveLine;
                Enabled = Rec."GPI Spiro Opportunity ID" <> '';
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Removes the Spiro opportunity link and its cached CRM snapshot from this packaging quote. It does not delete or modify the Spiro opportunity.';

                trigger OnAction()
                var
                    SpiroLinkMgt: Codeunit "GPI Spiro Link Mgt";
                begin
                    SpiroLinkMgt.UnlinkOpportunity(Rec);
                    CurrPage.Update(false);
                end;
            }
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
