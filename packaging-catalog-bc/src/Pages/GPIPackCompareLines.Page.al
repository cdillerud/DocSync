page 71019 "GPI Pack Comp Lines"
{
    PageType = ListPart;
    SourceTable = "GPI Pack Comp Line";
    ApplicationArea = All;
    Caption = 'Sourcing Comparison Candidates';
    DelayedInsert = true;
    AutoSplitKey = true;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field(Rank; Rec.Rank)
                {
                    ApplicationArea = All;
                }
                field("Product No."; Rec."Product No.")
                {
                    ApplicationArea = All;
                }
                field("BC Item No."; Rec."BC Item No.")
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
                field("FOB City"; Rec."FOB City")
                {
                    ApplicationArea = All;
                }
                field("FOB State/Province"; Rec."FOB State/Province")
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
                field("No. of Pallets"; Rec."No. of Pallets")
                {
                    ApplicationArea = All;
                }
                field("Supplier Unit Cost"; Rec."Supplier Unit Cost")
                {
                    ApplicationArea = All;
                }
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
                field("Freight Rate Entry No."; Rec."Freight Rate Entry No.")
                {
                    ApplicationArea = All;
                }
                field("Domestic Freight Total"; Rec."Domestic Freight Total")
                {
                    ApplicationArea = All;
                }
                field("Domestic Frt per Unit"; Rec."Domestic Frt per Unit")
                {
                    ApplicationArea = All;
                }
                field("Pallet Cost per Unit"; Rec."Pallet Cost per Unit")
                {
                    ApplicationArea = All;
                }
                field("Tariff per Unit"; Rec."Tariff per Unit")
                {
                    ApplicationArea = All;
                }
                field("Intl Freight per Unit"; Rec."Intl Freight per Unit")
                {
                    ApplicationArea = All;
                }
                field("Customs per Unit"; Rec."Customs per Unit")
                {
                    ApplicationArea = All;
                }
                field("Delivery per Unit"; Rec."Delivery per Unit")
                {
                    ApplicationArea = All;
                }
                field("Landed Cost per Unit"; Rec."Landed Cost per Unit")
                {
                    ApplicationArea = All;
                }
                field("Suggested Sell Price"; Rec."Suggested Sell Price")
                {
                    ApplicationArea = All;
                }
                field("Cost Above Best"; Rec."Cost Above Best")
                {
                    ApplicationArea = All;
                }
                field("Is Complete"; Rec."Is Complete")
                {
                    ApplicationArea = All;
                }
                field("Incomplete Reason"; Rec."Incomplete Reason")
                {
                    ApplicationArea = All;
                }
                field("Calculated At"; Rec."Calculated At")
                {
                    ApplicationArea = All;
                }
            }
        }
    }
}
