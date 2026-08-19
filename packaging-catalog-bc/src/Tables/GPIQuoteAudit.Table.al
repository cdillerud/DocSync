table 71008 "GPI Quote Audit"
{
    Caption = 'GPI Packaging Quote Audit';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; "Quote Entry No."; Integer)
        {
            Caption = 'Quote No.';
            TableRelation = "GPI Pack Quote"."Entry No.";
        }
        field(3; "Line No."; Integer)
        {
            Caption = 'Line No.';
        }
        field(4; "Event Type"; Enum "GPI Quote Audit Type")
        {
            Caption = 'Event Type';
        }
        field(5; "Event At"; DateTime)
        {
            Caption = 'Event At';
        }
        field(6; "Event By"; Text[100])
        {
            Caption = 'Event By';
        }
        field(7; "Quote Status"; Enum "GPI Pack Quote Stat")
        {
            Caption = 'Quote Status';
        }
        field(8; "Customer No."; Code[20])
        {
            Caption = 'Customer No.';
        }
        field(9; "Product No."; Code[20])
        {
            Caption = 'Gamer ID';
        }
        field(10; "BC Item No."; Code[20])
        {
            Caption = 'BC Item No.';
        }
        field(11; "UOM Code"; Code[10])
        {
            Caption = 'UOM';
        }
        field(12; Quantity; Decimal)
        {
            Caption = 'Quantity';
            DecimalPlaces = 0 : 5;
        }
        field(13; "Landed Cost per Unit"; Decimal)
        {
            Caption = 'Landed Cost per Unit';
            AutoFormatType = 2;
        }
        field(14; "Proposed Sell Price"; Decimal)
        {
            Caption = 'Proposed Sell Price per Unit';
            AutoFormatType = 2;
        }
        field(15; "Target Gross Margin %"; Decimal)
        {
            Caption = 'Target Gross Margin %';
            DecimalPlaces = 0 : 5;
        }
        field(16; "Calculated GP %"; Decimal)
        {
            Caption = 'Calculated Gross Margin %';
            DecimalPlaces = 0 : 5;
        }
        field(17; "Guardrail Status"; Enum "GPI Quote Guard Stat")
        {
            Caption = 'Guardrail Status';
        }
        field(18; "Needs Approval"; Boolean)
        {
            Caption = 'Needs Approval';
        }
        field(19; "Guardrail Approver"; Text[100])
        {
            Caption = 'Guardrail Approver';
        }
        field(20; "Pricing Rule Entry No."; Integer)
        {
            Caption = 'Pricing Rule Entry No.';
        }
        field(21; "Policy Fixed Sell Price"; Decimal)
        {
            Caption = 'Policy Fixed Sell Price';
            AutoFormatType = 2;
        }
        field(22; "Event Note"; Text[250])
        {
            Caption = 'Event Note';
        }
        field(23; "Previous Quantity"; Decimal)
        {
            Caption = 'Previous Quantity';
            DecimalPlaces = 0 : 5;
        }
        field(24; "Previous Landed Cost"; Decimal)
        {
            Caption = 'Previous Landed Cost per Unit';
            AutoFormatType = 2;
        }
        field(25; "Previous Sell Price"; Decimal)
        {
            Caption = 'Previous Proposed Sell Price';
            AutoFormatType = 2;
        }
        field(26; "Previous Target GM %"; Decimal)
        {
            Caption = 'Previous Target Gross Margin %';
            DecimalPlaces = 0 : 5;
        }
        field(27; "Previous Product No."; Code[20])
        {
            Caption = 'Previous Gamer ID';
        }
        field(28; "Previous BC Item No."; Code[20])
        {
            Caption = 'Previous BC Item No.';
        }
        field(29; "Previous UOM Code"; Code[10])
        {
            Caption = 'Previous UOM';
        }
        field(30; "Previous Guard Status"; Enum "GPI Quote Guard Stat")
        {
            Caption = 'Previous Guardrail Status';
        }
        field(31; "Previous Customer No."; Code[20])
        {
            Caption = 'Previous Customer No.';
        }
        field(32; "Quote Date"; Date)
        {
            Caption = 'Quote Date';
        }
        field(33; "Expiration Date"; Date)
        {
            Caption = 'Expiration Date';
        }
        field(34; "Quote Description"; Text[100])
        {
            Caption = 'Quote Description';
        }
        field(35; "Decision Note"; Text[250])
        {
            Caption = 'Decision Note';
        }
        field(36; "Previous Quote Date"; Date)
        {
            Caption = 'Previous Quote Date';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(QuoteEvent; "Quote Entry No.", "Event At", "Entry No.")
        {
        }
        key(QuoteLine; "Quote Entry No.", "Line No.", "Entry No.")
        {
        }
    }
}
