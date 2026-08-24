page 71107 "GPI Spiro Opp Lookup"
{
    PageType = List;
    SourceTable = "GPI Spiro Opp Cache";
    Caption = 'Spiro Opportunities';
    ApplicationArea = All;
    UsageCategory = None;
    Editable = false;
    InsertAllowed = false;
    DeleteAllowed = false;
    SourceTableView = sorting("Spiro Company ID", "Opportunity Name");

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field("Opportunity Name"; Rec."Opportunity Name")
                {
                    ApplicationArea = All;
                }
                field(Stage; Rec.Stage)
                {
                    ApplicationArea = All;
                }
                field(Owner; Rec.Owner)
                {
                    ApplicationArea = All;
                }                field("Assigned ISR"; Rec."Assigned ISR")
                {
                    ApplicationArea = All;
                }
                field(Probability; Rec.Probability)
                {
                    ApplicationArea = All;
                    Caption = 'Probability %';
                }
                field("Estimated Annual Volume"; Rec."Estimated Annual Volume")
                {
                    ApplicationArea = All;
                }
                field("Close Date"; Rec."Close Date")
                {
                    ApplicationArea = All;
                }
                field(Rating; Rec.Rating)
                {
                    ApplicationArea = All;
                }
                field("Spiro Opportunity ID"; Rec."Spiro Opportunity ID")
                {
                    ApplicationArea = All;
                }
                field("Spiro Company Name"; Rec."Spiro Company Name")
                {
                    ApplicationArea = All;
                }
                field("Refreshed At"; Rec."Refreshed At")
                {
                    ApplicationArea = All;
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(OpenSpiroOpportunity)
            {
                ApplicationArea = All;
                Caption = 'Open Spiro Opportunity';
                Image = LinkWeb;
                Enabled = Rec."Browser URL" <> '';

                trigger OnAction()
                begin
                    if Rec."Browser URL" = '' then
                        Error('No browser URL is available for this cached Spiro opportunity.');
                    Hyperlink(Rec."Browser URL");
                end;
            }
        }
    }
}
