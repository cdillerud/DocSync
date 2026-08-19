page 71031 "GPI Pack Prod Fact"
{
    PageType = CardPart;
    SourceTable = "GPI Pack Product";
    ApplicationArea = All;
    Caption = 'Product Snapshot';
    Editable = false;

    layout
    {
        area(Content)
        {
            group(Product)
            {
                Caption = 'Product';

                field("BC Item Description"; Rec."BC Item Description")
                {
                    ApplicationArea = All;
                    Caption = 'Description';
                }
                field("BC Item Category"; Rec."BC Item Category")
                {
                    ApplicationArea = All;
                    Caption = 'Category';
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
                field(Color; Rec.Color)
                {
                    ApplicationArea = All;
                }
                field(Style; Rec.Style)
                {
                    ApplicationArea = All;
                }
            }
            group(Supplier)
            {
                Caption = 'Supplier';

                field("Vendor Name"; Rec."Vendor Name")
                {
                    ApplicationArea = All;
                }
                field("Current Supplier Unit Cost"; Rec."Current Supplier Unit Cost")
                {
                    ApplicationArea = All;
                }
                field("Supplier Mold No."; Rec."Supplier Mold No.")
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
            }
            group(BusinessCentral)
            {
                Caption = 'Business Central';

                field("BC Item No."; Rec."BC Item No.")
                {
                    ApplicationArea = All;
                }
                field("BC Base UOM"; Rec."BC Base UOM")
                {
                    ApplicationArea = All;
                    Caption = 'Base UOM';
                }
                field("BC Item Blocked"; Rec."BC Item Blocked")
                {
                    ApplicationArea = All;
                }
            }
        }
    }
}
