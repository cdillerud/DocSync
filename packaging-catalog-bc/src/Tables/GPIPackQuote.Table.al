table 71006 "GPI Pack Quote"
{
    Caption = 'GPI Packaging Quote';
    DataClassification = CustomerContent;
    LookupPageId = "GPI Pack Quotes";
    DrillDownPageId = "GPI Pack Quotes";

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Quote No.';
            AutoIncrement = true;
        }
        field(2; "Quote Date"; Date)
        {
            Caption = 'Quote Date';
        }
        field(3; "Expiration Date"; Date)
        {
            Caption = 'Expiration Date';
        }
        field(4; "Customer No."; Code[20])
        {
            Caption = 'Customer No.';
            TableRelation = Customer."No.";
        }
        field(5; "Customer Name"; Text[100])
        {
            Caption = 'Customer Name';
            FieldClass = FlowField;
            CalcFormula = lookup(Customer.Name where("No." = field("Customer No.")));
            Editable = false;
        }
        field(6; Description; Text[100])
        {
            Caption = 'Description';
        }
        field(7; Status; Enum "GPI Pack Quote Stat")
        {
            Caption = 'Status';
        }
        field(8; "Line Count"; Integer)
        {
            Caption = 'Line Count';
            FieldClass = FlowField;
            CalcFormula = count("GPI Pack Quote Line" where("Quote Entry No." = field("Entry No.")));
            Editable = false;
        }
        field(9; "Approval Line Count"; Integer)
        {
            Caption = 'Lines Requiring Approval';
            FieldClass = FlowField;
            CalcFormula = count("GPI Pack Quote Line" where("Quote Entry No." = field("Entry No."), "Needs Approval" = const(true)));
            Editable = false;
        }
        field(10; "Last Evaluated At"; DateTime)
        {
            Caption = 'Last Evaluated At';
            Editable = false;
        }
        field(11; "Last Evaluated By"; Text[100])
        {
            Caption = 'Last Evaluated By';
            Editable = false;
        }
        field(12; Notes; Text[250])
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
        key(CustomerDate; "Customer No.", "Quote Date", "Entry No.")
        {
        }
    }

    trigger OnInsert()
    begin
        if "Quote Date" = 0D then
            "Quote Date" := WorkDate();
        Status := "GPI Pack Quote Stat"::Draft;
    end;

    trigger OnModify()
    begin
        if "Customer No." <> xRec."Customer No." then
            InvalidateLineEvaluations();
    end;

    trigger OnDelete()
    var
        QuoteLine: Record "GPI Pack Quote Line";
    begin
        QuoteLine.SetRange("Quote Entry No.", "Entry No.");
        QuoteLine.DeleteAll(true);
    end;

    local procedure InvalidateLineEvaluations()
    var
        QuoteLine: Record "GPI Pack Quote Line";
    begin
        QuoteLine.SetRange("Quote Entry No.", "Entry No.");
        if QuoteLine.FindSet(true) then
            repeat
                QuoteLine."Guardrail Status" := "GPI Quote Guard Stat"::"Not Evaluated";
                QuoteLine."Guardrail Message" := 'Customer changed. Re-evaluate this line.';
                QuoteLine."Guardrail Approver" := '';
                QuoteLine."Pricing Rule Entry No." := 0;
                QuoteLine."Policy Fixed Sell Price" := 0;
                QuoteLine."Needs Approval" := false;
                QuoteLine."Evaluated At" := 0DT;
                QuoteLine."Evaluated By" := '';
                QuoteLine.Modify(false);
            until QuoteLine.Next() = 0;

        Status := "GPI Pack Quote Stat"::Draft;
        "Last Evaluated At" := 0DT;
        "Last Evaluated By" := '';
    end;
}
