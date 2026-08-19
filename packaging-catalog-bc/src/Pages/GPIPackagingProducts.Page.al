page 71001 "GPI Pack Products"
{
    PageType = List;
    SourceTable = "GPI Pack Product";
    ApplicationArea = All;
    UsageCategory = Lists;
    Caption = 'GPI Packaging Catalog';
    CardPageId = "GPI Pack Prod Card";
    Editable = false;

    layout
    {
        area(Content)
        {
            repeater(Products)
            {
                field("No."; Rec."No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Gamer packaging product ID.';
                }
                field("BC Item No."; Rec."BC Item No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the linked Business Central item.';
                }
                field("BC Item Description"; Rec."BC Item Description")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows the current description from the linked Business Central item.';
                }
                field("BC Item Category"; Rec."BC Item Category")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows the current item category from the linked Business Central item.';
                }
                field(Material; Rec.Material)
                {
                    ApplicationArea = All;
                }
                field(Capacity; Rec.Capacity)
                {
                    ApplicationArea = All;
                }
                field("Capacity UOM"; Rec."Capacity UOM")
                {
                    ApplicationArea = All;
                }
                field(Finish; Rec.Finish)
                {
                    ApplicationArea = All;
                }
                field("Finish Type"; Rec."Finish Type")
                {
                    ApplicationArea = All;
                }
                field(Color; Rec.Color)
                {
                    ApplicationArea = All;
                }
                field(Style; Rec.Style)
                {
                    ApplicationArea = All;
                }
                field("Supplier Mold No."; Rec."Supplier Mold No.")
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
                field("Current Supplier Unit Cost"; Rec."Current Supplier Unit Cost")
                {
                    ApplicationArea = All;
                }
                field("Metric Ton Cost"; Rec."Metric Ton Cost")
                {
                    ApplicationArea = All;
                }
                field("BC Item Blocked"; Rec."BC Item Blocked")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows whether the linked Business Central item is currently blocked.';
                }
                field(Blocked; Rec.Blocked)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether this packaging catalog record is blocked.';
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(OpenBCItem)
            {
                ApplicationArea = All;
                Caption = 'Open BC Item';

                trigger OnAction()
                var
                    ItemRec: Record Item;
                begin
                    Rec.TestField("BC Item No.");
                    ItemRec.Get(Rec."BC Item No.");
                    Page.Run(Page::"Item Card", ItemRec);
                end;
            }
            action(OpenVendor)
            {
                ApplicationArea = All;
                Caption = 'Open Vendor';

                trigger OnAction()
                var
                    VendorRec: Record Vendor;
                begin
                    Rec.TestField("Vendor No.");
                    VendorRec.Get(Rec."Vendor No.");
                    Page.Run(Page::"Vendor Card", VendorRec);
                end;
            }
            action(NewLandedCost)
            {
                ApplicationArea = All;
                Caption = 'New Landed Cost';
                Image = Calculate;

                trigger OnAction()
                var
                    CostWork: Record "GPI Pack Cost Work";
                    CostMgt: Codeunit "GPI Pack Cost Mgt";
                begin
                    Rec.TestField("No.");
                    CostWork.Init();
                    CostWork."Product No." := Rec."No.";
                    CostWork."Calculation Date" := WorkDate();
                    CostMgt.InitializeFromProduct(CostWork);
                    CostWork.Insert(true);
                    Page.Run(Page::"GPI Pack Cost Calc", CostWork);
                end;
            }
            action(NewSourcingComparison)
            {
                ApplicationArea = All;
                Caption = 'New Sourcing Comparison';
                Image = Calculate;

                trigger OnAction()
                var
                    CompareHeader: Record "GPI Pack Compare";
                begin
                    Rec.TestField("No.");
                    CompareHeader.Init();
                    CompareHeader."Comparison Date" := WorkDate();
                    CompareHeader."Reference Product No." := Rec."No.";
                    CompareHeader.Description := CopyStr('Sourcing comparison for ' + Rec."No.", 1, MaxStrLen(CompareHeader.Description));
                    CompareHeader.Insert(true);
                    Page.Run(Page::"GPI Pack Comp Card", CompareHeader);
                end;
            }
            action(PriceHistory)
            {
                ApplicationArea = All;
                Caption = 'Supplier Price History';

                trigger OnAction()
                var
                    PriceHist: Record "GPI Pack Price Hist";
                begin
                    Rec.TestField("No.");
                    PriceHist.SetRange("Product No.", Rec."No.");
                    Page.Run(Page::"GPI Pack Price Hist", PriceHist);
                end;
            }
            action(NewProduct)
            {
                ApplicationArea = All;
                Caption = 'New Product';
                Image = New;
                RunObject = page "GPI Pack Prod Card";
                RunPageMode = Create;
            }
            action(PackagingQuotes)
            {
                ApplicationArea = All;
                Caption = 'Packaging Quotes';
                Image = Quote;
                RunObject = page "GPI Pack Quotes";
            }
            action(LandedCosts)
            {
                ApplicationArea = All;
                Caption = 'Landed Cost Worksheets';
                RunObject = page "GPI Pack Cost Works";
            }
            action(SourcingComparisons)
            {
                ApplicationArea = All;
                Caption = 'Sourcing Comparisons';
                RunObject = page "GPI Pack Compares";
            }
            action(VendorLocations)
            {
                ApplicationArea = All;
                Caption = 'Vendor Locations';
                RunObject = page "GPI Pack Vendor Locs";
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
