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
        field(13; "Decision Note"; Text[250])
        {
            Caption = 'Approval / Rejection Note';
        }
        field(14; "Decision At"; DateTime)
        {
            Caption = 'Decision At';
            Editable = false;
        }
        field(15; "Decision By"; Text[100])
        {
            Caption = 'Decision By';
            Editable = false;
        }
        field(16; "Audit Count"; Integer)
        {
            Caption = 'Audit Entries';
            FieldClass = FlowField;
            CalcFormula = count("GPI Quote Audit" where("Quote Entry No." = field("Entry No.")));
            Editable = false;
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
    var
        AuditMgt: Codeunit "GPI Quote Audit Mgt";
        CustomerChanged: Boolean;
        QuoteDateChanged: Boolean;
    begin
        CustomerChanged := "Customer No." <> xRec."Customer No.";
        QuoteDateChanged := "Quote Date" <> xRec."Quote Date";

        if xRec.Status in ["GPI Pack Quote Stat"::Approved, "GPI Pack Quote Stat"::Rejected, "GPI Pack Quote Stat"::Expired] then begin
            if LockedHeaderInputsChanged() then
                Error('Reopen the quote to Draft before changing approved, rejected, or expired quote values.');

            if "Decision Note" <> xRec."Decision Note" then
                Error('Reopen the quote to Draft before changing the recorded decision note.');
        end;

        if CustomerChanged or QuoteDateChanged then
            InvalidateLineEvaluations();

        if CustomerChanged then
            AuditMgt.LogCustomerChange(Rec, xRec."Customer No.");

        if QuoteDateChanged then
            AuditMgt.LogQuoteDateChange(Rec, xRec."Quote Date");
    end;

    trigger OnDelete()
    var
        QuoteLine: Record "GPI Pack Quote Line";
        AuditMgt: Codeunit "GPI Quote Audit Mgt";
        EnvironmentInformation: Codeunit "Environment Information";
    begin
        if (not EnvironmentInformation.IsSandbox()) and AuditMgt.HasDecisionAudit("Entry No.") then
            Error('This quote has an approval or rejection audit trail and cannot be deleted.');

        QuoteLine.SetRange("Quote Entry No.", "Entry No.");
        QuoteLine.DeleteAll(false);
        AuditMgt.DeleteQuoteAudit("Entry No.");
    end;

    local procedure InvalidateLineEvaluations()
    var
        QuoteLine: Record "GPI Pack Quote Line";
    begin
        QuoteLine.SetRange("Quote Entry No.", "Entry No.");
        if QuoteLine.FindSet(true) then
            repeat
                QuoteLine."Guardrail Status" := "GPI Quote Guard Stat"::"Not Evaluated";
                QuoteLine."Guardrail Message" := 'Quote header changed. Re-evaluate this line.';
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
        "Decision Note" := '';
        "Decision At" := 0DT;
        "Decision By" := '';
    end;

    local procedure LockedHeaderInputsChanged(): Boolean
    begin
        exit(
            ("Quote Date" <> xRec."Quote Date") or
            ("Expiration Date" <> xRec."Expiration Date") or
            ("Customer No." <> xRec."Customer No.") or
            (Description <> xRec.Description) or
            (Notes <> xRec.Notes));
    end;
}
