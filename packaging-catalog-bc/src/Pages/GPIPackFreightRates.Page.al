page 71004 "GPI Pack Frt Rates"
{
    PageType = List;
    SourceTable = "GPI Pack Frt Rate";
    ApplicationArea = All;
    UsageCategory = Lists;
    Caption = 'GPI Packaging Freight Rates';

    layout
    {
        area(Content)
        {
            repeater(Rates)
            {
                field("Origin Vendor No."; Rec."Origin Vendor No.")
                {
                    ApplicationArea = All;
                }
                field("Origin Location Code"; Rec."Origin Location Code")
                {
                    ApplicationArea = All;
                }
                field("Destination State"; Rec."Destination State")
                {
                    ApplicationArea = All;
                }
                field("Default Destination"; Rec."Default Destination")
                {
                    ApplicationArea = All;
                }
                field(Mode; Rec.Mode)
                {
                    ApplicationArea = All;
                }
                field("Rate per CWT"; Rec."Rate per CWT")
                {
                    ApplicationArea = All;
                }
                field("Minimum Charge"; Rec."Minimum Charge")
                {
                    ApplicationArea = All;
                }
                field("Fuel Surcharge %"; Rec."Fuel Surcharge %")
                {
                    ApplicationArea = All;
                }
                field("Effective Date"; Rec."Effective Date")
                {
                    ApplicationArea = All;
                }
                field(Notes; Rec.Notes)
                {
                    ApplicationArea = All;
                }
                field(Blocked; Rec.Blocked)
                {
                    ApplicationArea = All;
                }
            }
        }
    }
}
