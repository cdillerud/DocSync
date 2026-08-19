table 71007 "GPI Pack Quote Line"
{
    Caption = 'GPI Packaging Quote Line';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Quote Entry No."; Integer)
        {
            Caption = 'Quote No.';
            TableRelation = "GPI Pack Quote"."Entry No.";
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
                QuoteMgt: Codeunit "GPI Pack Quote Mgt";
            begin
                QuoteMgt.InitializeLineFromProduct(Rec);
            end;
        }
        field(4; Description; Text[100])
        {
            Caption = 'Description';
        }
        field(5; "BC Item No."; Code[20])
        {
            Caption = 'BC Item No.';
            TableRelation = Item."No.";

            trigger OnValidate()
            var
                QuoteMgt: Codeunit "GPI Pack Quote Mgt";
            begin
                QuoteMgt.SetDefaultUOMFromItem(Rec);
                QuoteMgt.RecalculateLine(Rec);
            end;
        }
        field(6; "UOM Code"; Code[10])
        {
            Caption = 'UOM';
            TableRelation = "Item Unit of Measure".Code where("Item No." = field("BC Item No."));

            trigger OnValidate()
            var
                QuoteMgt: Codeunit "GPI Pack Quote Mgt";
            begin
                QuoteMgt.RecalculateLine(Rec);
            end;
        }
        field(7; Quantity; Decimal)
        {
            Caption = 'Quantity';
            DecimalPlaces = 0 : 5;
            MinValue = 0;

            trigger OnValidate()
            var
                QuoteMgt: Codeunit "GPI Pack Quote Mgt";
            begin
                QuoteMgt.RecalculateLine(Rec);
            end;
        }
        field(8; "Cost Worksheet Entry No."; Integer)
        {
            Caption = 'Landed Cost Worksheet';
            TableRelation = "GPI Pack Cost Work"."Entry No.";

            trigger OnValidate()
            var
                QuoteMgt: Codeunit "GPI Pack Quote Mgt";
            begin
                QuoteMgt.InitializeLineFromCostWork(Rec);
            end;
        }
        field(9; "Landed Cost per Unit"; Decimal)
        {
            Caption = 'Landed Cost per Unit';
            AutoFormatType = 2;
            MinValue = 0;

            trigger OnValidate()
            var
                QuoteMgt: Codeunit "GPI Pack Quote Mgt";
            begin
                QuoteMgt.RecalculateLine(Rec);
            end;
        }
        field(10; "Proposed Sell Price"; Decimal)
        {
            Caption = 'Proposed Sell Price per Unit';
            AutoFormatType = 2;
            MinValue = 0;

            trigger OnValidate()
            var
                QuoteMgt: Codeunit "GPI Pack Quote Mgt";
            begin
                QuoteMgt.RecalculateLine(Rec);
            end;
        }
        field(11; "Target Gross Margin %"; Decimal)
        {
            Caption = 'Target Gross Margin %';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
            MaxValue = 99.99999;

            trigger OnValidate()
            var
                QuoteMgt: Codeunit "GPI Pack Quote Mgt";
            begin
                QuoteMgt.RecalculateLine(Rec);
            end;
        }
        field(12; "Suggested Sell Price"; Decimal)
        {
            Caption = 'Suggested Sell Price per Unit';
            AutoFormatType = 2;
            Editable = false;
        }
        field(13; "Calculated GP %"; Decimal)
        {
            Caption = 'Calculated Gross Margin %';
            DecimalPlaces = 0 : 5;
            Editable = false;
        }
        field(14; "Extended Landed Cost"; Decimal)
        {
            Caption = 'Extended Landed Cost';
            AutoFormatType = 2;
            Editable = false;
        }
        field(15; "Extended Sell"; Decimal)
        {
            Caption = 'Extended Sell';
            AutoFormatType = 2;
            Editable = false;
        }
        field(16; "Gross Profit Total"; Decimal)
        {
            Caption = 'Gross Profit Total';
            AutoFormatType = 2;
            Editable = false;
        }
        field(20; "Guardrail Status"; Enum "GPI Quote Guard Stat")
        {
            Caption = 'Guardrail Status';
            Editable = false;
        }
        field(21; "Guardrail Message"; Text[250])
        {
            Caption = 'Guardrail Message';
            Editable = false;
        }
        field(22; "Guardrail Approver"; Text[100])
        {
            Caption = 'Guardrail Approver';
            Editable = false;
        }
        field(23; "Pricing Rule Entry No."; Integer)
        {
            Caption = 'Pricing Rule Entry No.';
            TableRelation = "GPI Pricing Guard"."Entry No.";
            Editable = false;
        }
        field(24; "Policy Fixed Sell Price"; Decimal)
        {
            Caption = 'Policy Fixed Sell Price';
            AutoFormatType = 2;
            Editable = false;
        }
        field(25; "Needs Approval"; Boolean)
        {
            Caption = 'Needs Approval';
            Editable = false;
        }
        field(26; "Evaluated At"; DateTime)
        {
            Caption = 'Evaluated At';
            Editable = false;
        }
        field(27; "Evaluated By"; Text[100])
        {
            Caption = 'Evaluated By';
            Editable = false;
        }
    }

    keys
    {
        key(PK; "Quote Entry No.", "Line No.")
        {
            Clustered = true;
        }
        key(Product; "Product No.", "Quote Entry No.")
        {
        }
        key(BCItem; "BC Item No.", "Quote Entry No.")
        {
        }
    }

    trigger OnInsert()
    var
        QuoteLine: Record "GPI Pack Quote Line";
    begin
        if "Line No." = 0 then begin
            QuoteLine.SetRange("Quote Entry No.", "Quote Entry No.");
            if QuoteLine.FindLast() then
                "Line No." := QuoteLine."Line No." + 10000
            else
                "Line No." := 10000;
        end;

        "Guardrail Status" := "Guardrail Status"::"Not Evaluated";
    end;
}
