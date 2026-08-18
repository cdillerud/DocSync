page 71000 "GPI Packaging Product Card"
{
    PageType = Card;
    SourceTable = "GPI Packaging Product";
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
            part(PriceHistory; "GPI Pack Price History")
            {
                ApplicationArea = All;
                Caption = 'Price History';
                SubPageLink = "Product No." = field("No.");
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(RecalculateMetricTon)
            {
                ApplicationArea = All;
                Caption = 'Recalculate Metric Ton Cost';
                Image = Calculate;

                trigger OnAction()
                var
                    CatalogMgt: Codeunit "GPI Packaging Catalog Mgt.";
                begin
                    CatalogMgt.RecalculateMetricTonCost(Rec);
                    CurrPage.Update(false);
                end;
            }
            action(VendorLocations)
            {
                ApplicationArea = All;
                Caption = 'Vendor Locations';
                RunObject = page "GPI Pack Vendor Locations";
                RunPageLink = "Vendor No." = field("Vendor No.");
            }
            action(FreightRates)
            {
                ApplicationArea = All;
                Caption = 'Freight Rates';
                RunObject = page "GPI Pack Freight Rates";
                RunPageLink = "Origin Vendor No." = field("Vendor No.");
            }
        }
    }
}
