page 71001 "GPI Packaging Products"
{
    PageType = List;
    SourceTable = "GPI Packaging Product";
    ApplicationArea = All;
    UsageCategory = Lists;
    Caption = 'GPI Packaging Catalog';
    CardPageId = "GPI Packaging Product Card";
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
                field(Capacity; Rec.Capacity)
                {
                    ApplicationArea = All;
                }
                field("Capacity UOM"; Rec."Capacity UOM")
                {
                    ApplicationArea = All;
                }
                field(Color; Rec.Color)
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
                field("Transport Mode"; Rec."Transport Mode")
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
                field(Blocked; Rec.Blocked)
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
            action(NewProduct)
            {
                ApplicationArea = All;
                Caption = 'New Product';
                Image = New;
                RunObject = page "GPI Packaging Product Card";
                RunPageMode = Create;
            }
            action(VendorLocations)
            {
                ApplicationArea = All;
                Caption = 'Vendor Locations';
                RunObject = page "GPI Pack Vendor Locations";
            }
            action(FreightRates)
            {
                ApplicationArea = All;
                Caption = 'Freight Rates';
                RunObject = page "GPI Pack Freight Rates";
            }
        }
    }
}
