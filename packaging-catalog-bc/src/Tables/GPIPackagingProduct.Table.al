table 71000 "GPI Packaging Product"
{
    Caption = 'GPI Packaging Product';
    DataClassification = CustomerContent;
    LookupPageId = "GPI Packaging Products";
    DrillDownPageId = "GPI Packaging Products";

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
            TableRelation = "GPI Pack Vendor Location".Code where("Vendor No." = field("Vendor No."));
        }
        field(33; "FOB City"; Text[50])
        {
            Caption = 'FOB City';
            FieldClass = FlowField;
            CalcFormula = lookup("GPI Pack Vendor Location".City where("Vendor No." = field("Vendor No."), Code = field("Vendor Location Code")));
            Editable = false;
        }
        field(34; "FOB State/Province"; Code[20])
        {
            Caption = 'FOB State/Province';
            FieldClass = FlowField;
            CalcFormula = lookup("GPI Pack Vendor Location"."State/Province" where("Vendor No." = field("Vendor No."), Code = field("Vendor Location Code")));
            Editable = false;
        }
        field(40; "Transport Mode"; Enum "GPI Pack Transport Mode")
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
                CatalogMgt: Codeunit "GPI Packaging Catalog Mgt.";
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
                CatalogMgt: Codeunit "GPI Packaging Catalog Mgt.";
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
        key(Specification; Material, Style, Capacity, "Capacity UOM", Color)
        {
        }
    }

    trigger OnModify()
    var
        CatalogMgt: Codeunit "GPI Packaging Catalog Mgt.";
    begin
        if ("Current Supplier Unit Cost" <> xRec."Current Supplier Unit Cost") or
           ("Metric Ton Cost" <> xRec."Metric Ton Cost")
        then
            CatalogMgt.LogPriceChange(Rec, xRec);
    end;
}
