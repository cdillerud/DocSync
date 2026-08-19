table 71009 "GPI Pack Compare"
{
    Caption = 'GPI Packaging Sourcing Comparison';
    DataClassification = CustomerContent;
    LookupPageId = "GPI Pack Compares";
    DrillDownPageId = "GPI Pack Compares";

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Comparison No.';
            AutoIncrement = true;
        }
        field(2; "Comparison Date"; Date)
        {
            Caption = 'Comparison Date';
        }
        field(3; Description; Text[100])
        {
            Caption = 'Description';
        }
        field(4; "Reference Product No."; Code[20])
        {
            Caption = 'Reference Gamer ID';
            TableRelation = "GPI Pack Product"."No.";
        }
        field(5; "Destination State"; Code[20])
        {
            Caption = 'Destination State';
        }
        field(6; "Target Gross Margin %"; Decimal)
        {
            Caption = 'Target Gross Margin %';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
            MaxValue = 99.99999;
        }
        field(7; "Pallet Cost per Pallet"; Decimal)
        {
            Caption = 'Default Pallet Cost per Pallet';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(8; "Tariff %"; Decimal)
        {
            Caption = 'Default Tariff %';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
        }
        field(9; "Intl Freight Total"; Decimal)
        {
            Caption = 'Default International Freight Total';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(10; "Customs Total"; Decimal)
        {
            Caption = 'Default Customs Total';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(11; "Delivery Total"; Decimal)
        {
            Caption = 'Default Delivery Charge Total';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(20; "Candidate Count"; Integer)
        {
            Caption = 'Candidate Count';
            FieldClass = FlowField;
            CalcFormula = count("GPI Pack Comp Line" where("Compare Entry No." = field("Entry No.")));
            Editable = false;
        }
        field(21; "Ranked Count"; Integer)
        {
            Caption = 'Ranked Count';
            FieldClass = FlowField;
            CalcFormula = count("GPI Pack Comp Line" where("Compare Entry No." = field("Entry No."), "Is Complete" = const(true)));
            Editable = false;
        }
        field(22; "Last Calculated At"; DateTime)
        {
            Caption = 'Last Calculated At';
            Editable = false;
        }
        field(23; "Last Calculated By"; Text[100])
        {
            Caption = 'Last Calculated By';
            Editable = false;
        }
        field(24; Notes; Text[250])
        {
            Caption = 'Notes';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(ReferenceDate; "Reference Product No.", "Comparison Date", "Entry No.")
        {
        }
    }

    trigger OnInsert()
    begin
        if "Comparison Date" = 0D then
            "Comparison Date" := WorkDate();
    end;

    trigger OnModify()
    begin
        if CalculationInputsChanged() then
            InvalidateResults();
    end;

    trigger OnDelete()
    var
        CompareLine: Record "GPI Pack Comp Line";
    begin
        CompareLine.SetRange("Compare Entry No.", "Entry No.");
        CompareLine.DeleteAll(false);
    end;

    local procedure CalculationInputsChanged(): Boolean
    begin
        exit(
            ("Comparison Date" <> xRec."Comparison Date") or
            ("Reference Product No." <> xRec."Reference Product No.") or
            ("Destination State" <> xRec."Destination State") or
            ("Target Gross Margin %" <> xRec."Target Gross Margin %") or
            ("Pallet Cost per Pallet" <> xRec."Pallet Cost per Pallet") or
            ("Tariff %" <> xRec."Tariff %") or
            ("Intl Freight Total" <> xRec."Intl Freight Total") or
            ("Customs Total" <> xRec."Customs Total") or
            ("Delivery Total" <> xRec."Delivery Total"));
    end;

    local procedure InvalidateResults()
    var
        CompareLine: Record "GPI Pack Comp Line";
    begin
        CompareLine.SetRange("Compare Entry No.", "Entry No.");
        if CompareLine.FindSet(true) then
            repeat
                CompareLine.Rank := 0;
                CompareLine."Cost Above Best" := 0;
                CompareLine."Is Complete" := false;
                CompareLine."Incomplete Reason" := 'Comparison inputs changed. Recalculate the comparison.';
                CompareLine."Calculated At" := 0DT;
                CompareLine.Modify(false);
            until CompareLine.Next() = 0;

        "Last Calculated At" := 0DT;
        "Last Calculated By" := '';
    end;
}
