page 71018 "GPI Pack Comp Card"
{
    PageType = Card;
    SourceTable = "GPI Pack Compare";
    ApplicationArea = All;
    Caption = 'Packaging Sourcing Comparison';

    layout
    {
        area(Content)
        {
            group(General)
            {
                field("Entry No."; Rec."Entry No.")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Comparison Date"; Rec."Comparison Date")
                {
                    ApplicationArea = All;
                }
                field(Description; Rec.Description)
                {
                    ApplicationArea = All;
                }
                field("Reference Product No."; Rec."Reference Product No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the product whose Material, Style, Capacity, Capacity UOM, and Color are used to find exact packaging-spec candidates.';
                }
                field("Destination State"; Rec."Destination State")
                {
                    ApplicationArea = All;
                }
                field("Target Gross Margin %"; Rec."Target Gross Margin %")
                {
                    ApplicationArea = All;
                }
            }
            group(DefaultAssumptions)
            {
                Caption = 'Default Cost Assumptions';

                field("Pallet Cost per Pallet"; Rec."Pallet Cost per Pallet")
                {
                    ApplicationArea = All;
                }
                field("Tariff %"; Rec."Tariff %")
                {
                    ApplicationArea = All;
                }
                field("Intl Freight Total"; Rec."Intl Freight Total")
                {
                    ApplicationArea = All;
                }
                field("Customs Total"; Rec."Customs Total")
                {
                    ApplicationArea = All;
                }
                field("Delivery Total"; Rec."Delivery Total")
                {
                    ApplicationArea = All;
                }
            }
            group(Status)
            {
                field("Candidate Count"; Rec."Candidate Count")
                {
                    ApplicationArea = All;
                }
                field("Ranked Count"; Rec."Ranked Count")
                {
                    ApplicationArea = All;
                }
                field("Last Calculated At"; Rec."Last Calculated At")
                {
                    ApplicationArea = All;
                }
                field("Last Calculated By"; Rec."Last Calculated By")
                {
                    ApplicationArea = All;
                }
                field(Notes; Rec.Notes)
                {
                    ApplicationArea = All;
                    MultiLine = true;
                }
            }
            part(Candidates; "GPI Pack Comp Lines")
            {
                ApplicationArea = All;
                SubPageLink = "Compare Entry No." = field("Entry No.");
                UpdatePropagation = Both;
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(AddMatchingCandidates)
            {
                ApplicationArea = All;
                Caption = 'Add Exact Spec Matches';
                Image = Add;

                trigger OnAction()
                var
                    CompareMgt: Codeunit "GPI Pack Compare Mgt";
                begin
                    CurrPage.SaveRecord();
                    CompareMgt.AddMatchingCandidates(Rec);
                    CurrPage.Update(false);
                end;
            }
            action(ApplyHeaderDefaults)
            {
                ApplicationArea = All;
                Caption = 'Apply Header Defaults';
                Image = Refresh;

                trigger OnAction()
                var
                    CompareMgt: Codeunit "GPI Pack Compare Mgt";
                begin
                    CurrPage.SaveRecord();
                    CompareMgt.ApplyHeaderDefaults(Rec);
                    CurrPage.Update(false);
                end;
            }
            action(CalculateComparison)
            {
                ApplicationArea = All;
                Caption = 'Calculate and Rank';
                Image = Calculate;

                trigger OnAction()
                var
                    CompareMgt: Codeunit "GPI Pack Compare Mgt";
                begin
                    CurrPage.SaveRecord();
                    CompareMgt.CalculateComparison(Rec);
                    CurrPage.Update(false);
                end;
            }
        }
    }
}
