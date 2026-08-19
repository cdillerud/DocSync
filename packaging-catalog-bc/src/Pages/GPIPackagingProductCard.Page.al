page 71000 "GPI Pack Prod Card"
{
    PageType = Card;
    SourceTable = "GPI Pack Product";
    ApplicationArea = All;
    Caption = 'GPI Packaging Product';

    layout
    {
        area(Content)
        {
            group(General)
            {
                field("No."; Rec."No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Gamer packaging product ID.';
                }
                field("Supplier Mold No."; Rec."Supplier Mold No.")
                {
                    ApplicationArea = All;
                }
                field(Material; Rec.Material)
                {
                    ApplicationArea = All;
                }
                field(Style; Rec.Style)
                {
                    ApplicationArea = All;
                }
                field(Color; Rec.Color)
                {
                    ApplicationArea = All;
                }
                field(Blocked; Rec.Blocked)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether this packaging catalog record is blocked.';
                }
            }
            group(BCSource)
            {
                Caption = 'Business Central Item';

                field("BC Item No."; Rec."BC Item No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Links this packaging product to the Business Central item used as the source item and for posted-sales pricing context.';
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
                field("BC Base UOM"; Rec."BC Base UOM")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows the current base unit of measure from the linked Business Central item.';
                }
                field("BC Item Blocked"; Rec."BC Item Blocked")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows whether the linked Business Central item is currently blocked.';
                }
            }
            group(Specifications)
            {
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
                field(Packout; Rec.Packout)
                {
                    ApplicationArea = All;
                }
                field("Packout Type"; Rec."Packout Type")
                {
                    ApplicationArea = All;
                }
                field("Gram Weight"; Rec."Gram Weight")
                {
                    ApplicationArea = All;
                }
            }
            group(Sourcing)
            {
                field("Vendor No."; Rec."Vendor No.")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CurrPage.Update(false);
                    end;
                }
                field("Vendor Name"; Rec."Vendor Name")
                {
                    ApplicationArea = All;
                }
                field("Vendor Location Code"; Rec."Vendor Location Code")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CurrPage.Update(false);
                    end;
                }
                field("FOB City"; Rec."FOB City")
                {
                    ApplicationArea = All;
                }
                field("FOB State/Province"; Rec."FOB State/Province")
                {
                    ApplicationArea = All;
                }
                field("Transport Mode"; Rec."Transport Mode")
                {
                    ApplicationArea = All;
                }
                field("Full Load Quantity"; Rec."Full Load Quantity")
                {
                    ApplicationArea = All;
                }
                field("No. of Pallets"; Rec."No. of Pallets")
                {
                    ApplicationArea = All;
                }
                field("Pallet Quantity"; Rec."Pallet Quantity")
                {
                    ApplicationArea = All;
                }
                field("Qty. per Layer"; Rec."Qty. per Layer")
                {
                    ApplicationArea = All;
                }
                field("No. of Layers"; Rec."No. of Layers")
                {
                    ApplicationArea = All;
                }
            }
            group(Pricing)
            {
                field("Current Supplier Unit Cost"; Rec."Current Supplier Unit Cost")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the current supplier unit cost used by deterministic landed-cost and margin calculations.';
                }
                field("Metric Ton Cost"; Rec."Metric Ton Cost")
                {
                    ApplicationArea = All;
                }
                field("Price Effective Date"; Rec."Price Effective Date")
                {
                    ApplicationArea = All;
                }
                field("Price Change Note"; Rec."Price Change Note")
                {
                    ApplicationArea = All;
                }
            }
            group(Documents)
            {
                field("Product Image"; Rec."Product Image")
                {
                    ApplicationArea = All;
                }
                field("Product Drawing"; Rec."Product Drawing")
                {
                    ApplicationArea = All;
                }
                field("Drawing File Name"; Rec."Drawing File Name")
                {
                    ApplicationArea = All;
                }
            }
            part(PriceHistory; "GPI Pack Price Hist")
            {
                ApplicationArea = All;
                Caption = 'Supplier Price History';
                SubPageLink = "Product No." = field("No.");
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
            action(RecalculateMetricTon)
            {
                ApplicationArea = All;
                Caption = 'Recalculate Metric Ton Cost';
                Image = Calculate;

                trigger OnAction()
                var
                    CatalogMgt: Codeunit "GPI Pack Catalog Mgt";
                begin
                    CatalogMgt.RecalculateMetricTonCost(Rec);
                    CurrPage.Update(false);
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
            action(LandedCosts)
            {
                ApplicationArea = All;
                Caption = 'Landed Cost Worksheets';
                RunObject = page "GPI Pack Cost Works";
                RunPageLink = "Product No." = field("No.");
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
            action(SourcingComparisons)
            {
                ApplicationArea = All;
                Caption = 'Sourcing Comparisons';
                RunObject = page "GPI Pack Compares";
                RunPageLink = "Reference Product No." = field("No.");
            }
            action(VendorLocations)
            {
                ApplicationArea = All;
                Caption = 'Vendor Locations';
                RunObject = page "GPI Pack Vendor Locs";
                RunPageLink = "Vendor No." = field("Vendor No.");
            }
            action(FreightRates)
            {
                ApplicationArea = All;
                Caption = 'Freight Rates';
                RunObject = page "GPI Pack Frt Rates";
                RunPageLink = "Origin Vendor No." = field("Vendor No.");
            }
            action(PackagingQuotes)
            {
                ApplicationArea = All;
                Caption = 'Packaging Quotes';
                Image = Quote;
                RunObject = page "GPI Pack Quotes";
            }
        }
    }
}
