table 71010 "GPI Pack Comp Line"
{
    Caption = 'GPI Packaging Sourcing Comparison Line';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Compare Entry No."; Integer)
        {
            Caption = 'Comparison No.';
            TableRelation = "GPI Pack Compare"."Entry No.";
        }
        field(2; "Line No."; Integer)
        {
            Caption = 'Line No.';
        }
        field(3; "Product No."; Code[20])
        {
            Caption = 'Gamer ID';
            TableRelation = "GPI Pack Product"."No.";

            trigger OnValidate()
            var
                CompareMgt: Codeunit "GPI Pack Compare Mgt";
            begin
                CompareMgt.InitializeCandidate(Rec);
            end;
        }
        field(4; "BC Item No."; Code[20])
        {
            Caption = 'BC Item No.';
            Editable = false;
        }
        field(5; "Vendor No."; Code[20])
        {
            Caption = 'Vendor No.';
            Editable = false;
        }
        field(6; "Vendor Name"; Text[100])
        {
            Caption = 'Vendor Name';
            FieldClass = FlowField;
            CalcFormula = lookup(Vendor.Name where("No." = field("Vendor No.")));
            Editable = false;
        }
        field(7; "Vendor Location Code"; Code[20])
        {
            Caption = 'Vendor FOB Location';
            Editable = false;
        }
        field(8; "FOB City"; Text[50])
        {
            Caption = 'FOB City';
            FieldClass = FlowField;
            CalcFormula = lookup("GPI Pack Vendor Loc".City where("Vendor No." = field("Vendor No."), Code = field("Vendor Location Code")));
            Editable = false;
        }
        field(9; "FOB State/Province"; Code[20])
        {
            Caption = 'FOB State/Province';
            FieldClass = FlowField;
            CalcFormula = lookup("GPI Pack Vendor Loc"."State/Province" where("Vendor No." = field("Vendor No."), Code = field("Vendor Location Code")));
            Editable = false;
        }
        field(10; Mode; Enum "GPI Pack Transport")
        {
            Caption = 'Transport Mode';
            Editable = false;
        }
        field(11; Quantity; Decimal)
        {
            Caption = 'Comparison Quantity';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
        }
        field(12; "Gram Weight"; Decimal)
        {
            Caption = 'Gram Weight';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
            Editable = false;
        }
        field(13; "No. of Pallets"; Decimal)
        {
            Caption = 'No. of Pallets';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
        }
        field(14; "Supplier Unit Cost"; Decimal)
        {
            Caption = 'Supplier Unit Cost';
            AutoFormatType = 2;
            MinValue = 0;
            Editable = false;
        }
        field(15; "Pallet Cost per Pallet"; Decimal)
        {
            Caption = 'Pallet Cost per Pallet';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(16; "Tariff %"; Decimal)
        {
            Caption = 'Tariff %';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
        }
        field(17; "Intl Freight Total"; Decimal)
        {
            Caption = 'International Freight Total';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(18; "Customs Total"; Decimal)
        {
            Caption = 'Customs Total';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(19; "Delivery Total"; Decimal)
        {
            Caption = 'Delivery Charge Total';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(30; "Shipment CWT"; Decimal)
        {
            Caption = 'Shipment CWT';
            DecimalPlaces = 0 : 5;
            Editable = false;
        }
        field(31; "Freight Rate Entry No."; Integer)
        {
            Caption = 'Freight Rate Entry No.';
            Editable = false;
        }
        field(32; "Rate per CWT"; Decimal)
        {
            Caption = 'Rate per CWT';
            AutoFormatType = 2;
            Editable = false;
        }
        field(33; "Minimum Charge"; Decimal)
        {
            Caption = 'Minimum Charge';
            AutoFormatType = 2;
            Editable = false;
        }
        field(34; "Fuel Surcharge %"; Decimal)
        {
            Caption = 'Fuel Surcharge %';
            DecimalPlaces = 0 : 5;
            Editable = false;
        }
        field(35; "Domestic Freight Total"; Decimal)
        {
            Caption = 'Domestic Freight Total';
            AutoFormatType = 2;
            Editable = false;
        }
        field(36; "Domestic Frt per Unit"; Decimal)
        {
            Caption = 'Domestic Freight per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(37; "Pallet Cost per Unit"; Decimal)
        {
            Caption = 'Pallet Cost per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(38; "Tariff per Unit"; Decimal)
        {
            Caption = 'Tariff per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(39; "Intl Freight per Unit"; Decimal)
        {
            Caption = 'International Freight per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(40; "Customs per Unit"; Decimal)
        {
            Caption = 'Customs per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(41; "Delivery per Unit"; Decimal)
        {
            Caption = 'Delivery per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(42; "Landed Cost per Unit"; Decimal)
        {
            Caption = 'Landed Cost per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(43; "Suggested Sell Price"; Decimal)
        {
            Caption = 'Suggested Sell Price per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(44; Rank; Integer)
        {
            Caption = 'Rank';
            Editable = false;
        }
        field(45; "Cost Above Best"; Decimal)
        {
            Caption = 'Cost Above Best per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(46; "Is Complete"; Boolean)
        {
            Caption = 'Rankable';
            Editable = false;
        }
        field(47; "Incomplete Reason"; Text[250])
        {
            Caption = 'Incomplete Reason';
            Editable = false;
        }
        field(48; "Calculated At"; DateTime)
        {
            Caption = 'Calculated At';
            Editable = false;
        }
    }

    keys
    {
        key(PK; "Compare Entry No.", "Line No.")
        {
            Clustered = true;
        }
        key(Product; "Compare Entry No.", "Product No.")
        {
        }
        key(CompleteCost; "Compare Entry No.", "Is Complete", "Landed Cost per Unit", "Line No.")
        {
        }
    }

    trigger OnInsert()
    var
        CompareHeader: Record "GPI Pack Compare";
        CompareLine: Record "GPI Pack Comp Line";
    begin
        CompareHeader.Get("Compare Entry No.");

        if "Line No." = 0 then begin
            CompareLine.SetRange("Compare Entry No.", "Compare Entry No.");
            if CompareLine.FindLast() then
                "Line No." := CompareLine."Line No." + 10000
            else
                "Line No." := 10000;
        end;
    end;

    trigger OnModify()
    var
        CompareHeader: Record "GPI Pack Compare";
    begin
        if not InputsChanged() then
            exit;

        ClearResults();

        if CompareHeader.Get("Compare Entry No.") then begin
            CompareHeader."Last Calculated At" := 0DT;
            CompareHeader."Last Calculated By" := '';
            CompareHeader.Modify(false);
        end;
    end;

    local procedure InputsChanged(): Boolean
    begin
        exit(
            ("Product No." <> xRec."Product No.") or
            (Quantity <> xRec.Quantity) or
            ("No. of Pallets" <> xRec."No. of Pallets") or
            ("Pallet Cost per Pallet" <> xRec."Pallet Cost per Pallet") or
            ("Tariff %" <> xRec."Tariff %") or
            ("Intl Freight Total" <> xRec."Intl Freight Total") or
            ("Customs Total" <> xRec."Customs Total") or
            ("Delivery Total" <> xRec."Delivery Total"));
    end;

    local procedure ClearResults()
    begin
        "Shipment CWT" := 0;
        "Freight Rate Entry No." := 0;
        "Rate per CWT" := 0;
        "Minimum Charge" := 0;
        "Fuel Surcharge %" := 0;
        "Domestic Freight Total" := 0;
        "Domestic Frt per Unit" := 0;
        "Pallet Cost per Unit" := 0;
        "Tariff per Unit" := 0;
        "Intl Freight per Unit" := 0;
        "Customs per Unit" := 0;
        "Delivery per Unit" := 0;
        "Landed Cost per Unit" := 0;
        "Suggested Sell Price" := 0;
        Rank := 0;
        "Cost Above Best" := 0;
        "Is Complete" := false;
        "Incomplete Reason" := '';
        "Calculated At" := 0DT;
    end;
}
