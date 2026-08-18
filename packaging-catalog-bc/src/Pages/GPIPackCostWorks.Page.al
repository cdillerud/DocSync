page 71005 "GPI Pack Cost Works"
{
    PageType = List;
    SourceTable = "GPI Pack Cost Work";
    ApplicationArea = All;
    UsageCategory = Tasks;
    Caption = 'GPI Packaging Landed Cost Worksheets';
    CardPageId = "GPI Pack Cost Calc";

    layout
    {
        area(Content)
        {
            repeater(Worksheets)
            {
                field("Entry No."; Rec."Entry No.")
                {
                    ApplicationArea = All;
                }
                field("Product No."; Rec."Product No.")
                {
                    ApplicationArea = All;
                }
                field("Calculation Date"; Rec."Calculation Date")
                {
                    ApplicationArea = All;
                }
                field("Vendor No."; Rec."Vendor No.")
                {
                    ApplicationArea = All;
                }
                field("Vendor Name"; Rec."Vendor Name")
                {
                    ApplicationArea = All;
                }
                field("Vendor Location Code"; Rec."Vendor Location Code")
                {
                    ApplicationArea = All;
                }
                field("Destination State"; Rec."Destination State")
                {
                    ApplicationArea = All;
                }
                field(Mode; Rec.Mode)
                {
                    ApplicationArea = All;
                }
                field(Quantity; Rec.Quantity)
                {
                    ApplicationArea = All;
                }
                field("Unit Cost"; Rec."Unit Cost")
                {
                    ApplicationArea = All;
                }
                field("Domestic Freight Total"; Rec."Domestic Freight Total")
                {
                    ApplicationArea = All;
                }
                field("Landed Cost per Unit"; Rec."Landed Cost per Unit")
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
            action(NewWorksheet)
            {
                ApplicationArea = All;
                Caption = 'New Landed Cost Worksheet';
                Image = New;
                RunObject = page "GPI Pack Cost Calc";
                RunPageMode = Create;
            }
            action(FreightRates)
            {
                ApplicationArea = All;
                Caption = 'Freight Rates';
                RunObject = page "GPI Pack Frt Rates";
            }
        }
    }
}
