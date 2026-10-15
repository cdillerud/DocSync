table 71000 "GPI Pack Product"
{
    Caption = 'GPI Packaging Product';
    DataClassification = CustomerContent;
    LookupPageId = "GPI Pack Products";
    DrillDownPageId = "GPI Pack Products";

    fields
    {
        field(1; "No."; Code[20])
        {
            Caption = 'Gamer ID';
            NotBlank = true;
        }
        field(2; "Supplier Mold No."; Code[50])
        {
            Caption = 'Supplier Mold No.';
        }
        field(10; Material; Text[30])
        {
            Caption = 'Material';
        }
        field(11; Capacity; Decimal)
        {
            Caption = 'Capacity';
            DecimalPlaces = 0 : 5;
        }
        field(12; "Capacity UOM"; Code[10])
        {
            Caption = 'Capacity UOM';
        }
        field(13; Finish; Text[50])
        {
            Caption = 'Finish';
        }
        field(14; "Finish Type"; Text[30])
        {
            Caption = 'Finish Type';
        }
        field(15; Color; Text[30])
        {
            Caption = 'Color';
        }
        field(16; Style; Text[50])
        {
            Caption = 'Style';
        }
        field(17; Packout; Text[100])
        {
            Caption = 'Packout';
        }
        field(18; "Packout Type"; Enum "GPI Packout Type")
        {
            Caption = 'Packout Type';
        }
        field(19; "BC Item No."; Code[20])
        {
            Caption = 'BC Item No.';
            TableRelation = Item."No.";
        }
        field(20; "BC Item Description"; Text[100])
        {
            Caption = 'BC Item Description';
            FieldClass = FlowField;
            CalcFormula = lookup(Item.Description where("No." = field("BC Item No.")));
            Editable = false;
        }
        field(21; "BC Item Category"; Code[20])
        {
            Caption = 'BC Item Category';
            FieldClass = FlowField;
            CalcFormula = lookup(Item."Item Category Code" where("No." = field("BC Item No.")));
            Editable = false;
        }
        field(22; "BC Base UOM"; Code[10])
        {
            Caption = 'BC Base UOM';
            FieldClass = FlowField;
            CalcFormula = lookup(Item."Base Unit of Measure" where("No." = field("BC Item No.")));
            Editable = false;
        }
        field(23; "BC Item Blocked"; Boolean)
        {
            Caption = 'BC Item Blocked';
            FieldClass = FlowField;
            CalcFormula = lookup(Item.Blocked where("No." = field("BC Item No.")));
            Editable = false;
        }
        field(30; "Vendor No."; Code[20])
        {
            Caption = 'Vendor No.';
            TableRelation = Vendor."No.";

            trigger OnValidate()
            begin
                if "Vendor No." <> xRec."Vendor No." then
                    "Vendor Location Code" := '';
            end;
        }
        field(31; "Vendor Name"; Text[100])
        {
            Caption = 'Vendor Name';
            FieldClass = FlowField;
            CalcFormula = lookup(Vendor.Name where("No." = field("Vendor No.")));
            Editable = false;
        }
        field(32; "Vendor Location Code"; Code[20])
        {
            Caption = 'Vendor FOB Location';
            TableRelation = "GPI Pack Vendor Loc".Code where("Vendor No." = field("Vendor No."));
        }
        field(33; "FOB City"; Text[50])
        {
            Caption = 'FOB City';
            FieldClass = FlowField;
            CalcFormula = lookup("GPI Pack Vendor Loc".City where("Vendor No." = field("Vendor No."), Code = field("Vendor Location Code")));
            Editable = false;
        }
        field(34; "FOB State/Province"; Code[20])
        {
            Caption = 'FOB State/Province';
            FieldClass = FlowField;
            CalcFormula = lookup("GPI Pack Vendor Loc"."State/Province" where("Vendor No." = field("Vendor No."), Code = field("Vendor Location Code")));
            Editable = false;
        }
        field(40; "Transport Mode"; Enum "GPI Pack Transport")
        {
            Caption = 'TL or CNTR';
        }
        field(41; "Full Load Quantity"; Decimal)
        {
            Caption = 'Full Load Quantity';
            DecimalPlaces = 0 : 5;
        }
        field(42; "No. of Pallets"; Decimal)
        {
            Caption = 'No. of Pallets';
            DecimalPlaces = 0 : 5;
        }
        field(43; "Pallet Quantity"; Decimal)
        {
            Caption = 'Pallet Quantity';
            DecimalPlaces = 0 : 5;
        }
        field(44; "Qty. per Layer"; Decimal)
        {
            Caption = 'Qty. per Layer';
            DecimalPlaces = 0 : 5;
        }
        field(45; "No. of Layers"; Decimal)
        {
            Caption = 'No. of Layers';
            DecimalPlaces = 0 : 5;
        }
        field(46; "Gram Weight"; Decimal)
        {
            Caption = 'Gram Weight';
            DecimalPlaces = 0 : 5;

            trigger OnValidate()
            var
                CatalogMgt: Codeunit "GPI Pack Catalog Mgt";
            begin
                "Metric Ton Cost" := CatalogMgt.CalculateMetricTonCost("Current Supplier Unit Cost", "Gram Weight");
            end;
        }
        field(50; "Current Supplier Unit Cost"; Decimal)
        {
            Caption = 'Current Supplier Unit Cost';
            AutoFormatType = 2;

            trigger OnValidate()
            var
                CatalogMgt: Codeunit "GPI Pack Catalog Mgt";
            begin
                if "Price Effective Date" = 0D then
                    "Price Effective Date" := WorkDate();
                "Metric Ton Cost" := CatalogMgt.CalculateMetricTonCost("Current Supplier Unit Cost", "Gram Weight");
            end;
        }
        field(51; "Metric Ton Cost"; Decimal)
        {
            Caption = 'Metric Ton Cost';
            AutoFormatType = 2;
            Editable = false;
        }
        field(52; "Price Effective Date"; Date)
        {
            Caption = 'Price Effective Date';
        }
        field(53; "Price Change Note"; Text[250])
        {
            Caption = 'Price Change Note';
        }
        field(60; "Product Image"; MediaSet)
        {
            Caption = 'Product Image';
        }
        field(61; "Product Drawing"; Media)
        {
            Caption = 'Product Drawing';
        }
        field(62; "Drawing File Name"; Text[250])
        {
            Caption = 'Drawing File Name';
        }
        field(70; Blocked; Boolean)
        {
            Caption = 'Blocked';
        }
        // RFQ Masterbook columns with no earlier home in the catalog (0.49.0.0).
        field(80; Incoterm; Code[10])
        {
            Caption = 'Incoterm';
            ToolTip = 'Specifies the supplier Incoterm for this option, such as EXW, FOB or CIF.';
        }
        field(81; "Incoterm Location"; Text[100])
        {
            Caption = 'Incoterm Location';
            ToolTip = 'Specifies the named place for the Incoterm as the supplier quotes it, such as Busan or Winchester, IN or Muncie, IN.';
        }
        field(82; "Trade Scope"; Enum "GPI Pack Trade Scope")
        {
            Caption = 'Domestic / International';
            ToolTip = 'Specifies whether the option is sourced domestically or imported, as the RFQ Masterbook classifies it.';
        }
        field(83; MOQ; Text[50])
        {
            Caption = 'MOQ';
            ToolTip = 'Specifies the supplier minimum order as quoted, such as 300,000, 1 container or Made to Order.';
        }
        field(84; "MOQ Quantity"; Decimal)
        {
            Caption = 'MOQ Quantity';
            DecimalPlaces = 0 : 5;
            ToolTip = 'Specifies the minimum order quantity in units when the supplier quotes a number.';
        }
        field(85; "Tariff per Unit"; Decimal)
        {
            Caption = 'Tariff per Unit';
            AutoFormatType = 2;
            ToolTip = 'Specifies the tariff amount per unit from the RFQ Masterbook. Reference only: landed-cost calculations do not use it.';
        }
        field(86; "Drawing URL"; Text[2048])
        {
            Caption = 'Drawing URL';
            ExtendedDatatype = URL;
            ToolTip = 'Specifies a link to the product drawing, such as a SharePoint PDF.';
        }
        field(87; "Supplier Name"; Text[100])
        {
            Caption = 'Supplier Name';
            ToolTip = 'Specifies the supplier name as quoted. Used when the supplier is not yet set up as a Business Central vendor.';
        }
    }

    keys
    {
        key(PK; "No.")
        {
            Clustered = true;
        }
        key(Vendor; "Vendor No.", "Vendor Location Code")
        {
        }
        key(BCItem; "BC Item No.")
        {
        }
        key(Specification; Material, Style, Capacity, "Capacity UOM", Color)
        {
        }
    }

    trigger OnModify()
    var
        CatalogMgt: Codeunit "GPI Pack Catalog Mgt";
    begin
        if ("Current Supplier Unit Cost" <> xRec."Current Supplier Unit Cost") or
           ("Metric Ton Cost" <> xRec."Metric Ton Cost")
        then
            CatalogMgt.LogPriceChange(Rec, xRec);
    end;
}
