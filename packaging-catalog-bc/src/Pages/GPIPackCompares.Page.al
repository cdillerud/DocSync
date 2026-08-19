page 71017 "GPI Pack Compares"
{
    PageType = List;
    SourceTable = "GPI Pack Compare";
    ApplicationArea = All;
    UsageCategory = Lists;
    Caption = 'Packaging Sourcing Comparisons';
    CardPageId = "GPI Pack Comp Card";

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field("Entry No."; Rec."Entry No.")
                {
                    ApplicationArea = All;
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
                }
                field("Destination State"; Rec."Destination State")
                {
                    ApplicationArea = All;
                }
                field("Target Gross Margin %"; Rec."Target Gross Margin %")
                {
                    ApplicationArea = All;
                }
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
            }
        }
    }
}
