codeunit 71003 "GPI Quote Audit Mgt"
{
    Permissions = tabledata "GPI Quote Audit" = RIMD;

    procedure LogQuoteSnapshot(QuoteHeader: Record "GPI Pack Quote"; EventType: Enum "GPI Quote Audit Type"; EventNote: Text)
    var
        QuoteLine: Record "GPI Pack Quote Line";
        PreviousLine: Record "GPI Pack Quote Line";
    begin
        InsertHeaderAudit(QuoteHeader, EventType, EventNote, '', 0D);
        Clear(PreviousLine);

        QuoteLine.SetRange("Quote Entry No.", QuoteHeader."Entry No.");
        if QuoteLine.FindSet() then
            repeat
                InsertLineAudit(QuoteHeader, QuoteLine, EventType, EventNote, PreviousLine);
            until QuoteLine.Next() = 0;
    end;

    procedure LogPricingChange(QuoteLine: Record "GPI Pack Quote Line"; PreviousLine: Record "GPI Pack Quote Line")
    var
        QuoteHeader: Record "GPI Pack Quote";
    begin
        if not QuoteHeader.Get(QuoteLine."Quote Entry No.") then
            exit;

        InsertLineAudit(
            QuoteHeader,
            QuoteLine,
            "GPI Quote Audit Type"::"Pricing Changed",
            'Pricing inputs changed after a prior guardrail evaluation or review state.',
            PreviousLine);
    end;

    procedure LogLineChange(QuoteLine: Record "GPI Pack Quote Line"; PreviousLine: Record "GPI Pack Quote Line")
    var
        QuoteHeader: Record "GPI Pack Quote";
    begin
        if not QuoteHeader.Get(QuoteLine."Quote Entry No.") then
            exit;

        InsertLineAudit(
            QuoteHeader,
            QuoteLine,
            "GPI Quote Audit Type"::"Quote Changed",
            'Quote line content changed after a prior guardrail evaluation or review state.',
            PreviousLine);
    end;

    procedure LogCustomerChange(QuoteHeader: Record "GPI Pack Quote"; PreviousCustomerNo: Code[20])
    var
        EventNote: Text[250];
    begin
        EventNote := CopyStr(
            StrSubstNo('Customer changed from %1 to %2. Existing line evaluations were invalidated.', PreviousCustomerNo, QuoteHeader."Customer No."),
            1,
            MaxStrLen(EventNote));
        InsertHeaderAudit(QuoteHeader, "GPI Quote Audit Type"::"Customer Changed", EventNote, PreviousCustomerNo, 0D);
    end;

    procedure LogQuoteDateChange(QuoteHeader: Record "GPI Pack Quote"; PreviousQuoteDate: Date)
    var
        EventNote: Text[250];
    begin
        EventNote := CopyStr(
            StrSubstNo('Quote Date changed from %1 to %2. Effective-dated guardrail evaluations were invalidated.', PreviousQuoteDate, QuoteHeader."Quote Date"),
            1,
            MaxStrLen(EventNote));
        InsertHeaderAudit(QuoteHeader, "GPI Quote Audit Type"::"Quote Changed", EventNote, '', PreviousQuoteDate);
    end;

    procedure HasDecisionAudit(QuoteEntryNo: Integer): Boolean
    var
        QuoteAudit: Record "GPI Quote Audit";
    begin
        QuoteAudit.SetRange("Quote Entry No.", QuoteEntryNo);
        QuoteAudit.SetRange("Event Type", "GPI Quote Audit Type"::Approved, "GPI Quote Audit Type"::Rejected);
        exit(not QuoteAudit.IsEmpty());
    end;

    procedure DeleteQuoteAudit(QuoteEntryNo: Integer)
    var
        QuoteAudit: Record "GPI Quote Audit";
    begin
        QuoteAudit.SetRange("Quote Entry No.", QuoteEntryNo);
        QuoteAudit.DeleteAll(false);
    end;

    local procedure InsertHeaderAudit(QuoteHeader: Record "GPI Pack Quote"; EventType: Enum "GPI Quote Audit Type"; EventNote: Text; PreviousCustomerNo: Code[20]; PreviousQuoteDate: Date)
    var
        QuoteAudit: Record "GPI Quote Audit";
    begin
        QuoteAudit.Init();
        QuoteAudit."Quote Entry No." := QuoteHeader."Entry No.";
        QuoteAudit."Line No." := 0;
        QuoteAudit."Event Type" := EventType;
        QuoteAudit."Event At" := CurrentDateTime();
        QuoteAudit."Event By" := CopyStr(UserId(), 1, MaxStrLen(QuoteAudit."Event By"));
        QuoteAudit."Quote Status" := QuoteHeader.Status;
        QuoteAudit."Customer No." := QuoteHeader."Customer No.";
        QuoteAudit."Quote Date" := QuoteHeader."Quote Date";
        QuoteAudit."Expiration Date" := QuoteHeader."Expiration Date";
        QuoteAudit."Quote Description" := QuoteHeader.Description;
        QuoteAudit."Decision Note" := QuoteHeader."Decision Note";
        QuoteAudit."Event Note" := CopyStr(EventNote, 1, MaxStrLen(QuoteAudit."Event Note"));
        QuoteAudit."Previous Customer No." := PreviousCustomerNo;
        QuoteAudit."Previous Quote Date" := PreviousQuoteDate;
        QuoteAudit.Insert(true);
    end;

    local procedure InsertLineAudit(QuoteHeader: Record "GPI Pack Quote"; QuoteLine: Record "GPI Pack Quote Line"; EventType: Enum "GPI Quote Audit Type"; EventNote: Text; PreviousLine: Record "GPI Pack Quote Line")
    var
        QuoteAudit: Record "GPI Quote Audit";
    begin
        QuoteAudit.Init();
        QuoteAudit."Quote Entry No." := QuoteHeader."Entry No.";
        QuoteAudit."Line No." := QuoteLine."Line No.";
        QuoteAudit."Event Type" := EventType;
        QuoteAudit."Event At" := CurrentDateTime();
        QuoteAudit."Event By" := CopyStr(UserId(), 1, MaxStrLen(QuoteAudit."Event By"));
        QuoteAudit."Quote Status" := QuoteHeader.Status;
        QuoteAudit."Customer No." := QuoteHeader."Customer No.";
        QuoteAudit."Quote Date" := QuoteHeader."Quote Date";
        QuoteAudit."Expiration Date" := QuoteHeader."Expiration Date";
        QuoteAudit."Quote Description" := QuoteHeader.Description;
        QuoteAudit."Decision Note" := QuoteHeader."Decision Note";
        QuoteAudit."Product No." := QuoteLine."Product No.";
        QuoteAudit."BC Item No." := QuoteLine."BC Item No.";
        QuoteAudit."UOM Code" := QuoteLine."UOM Code";
        QuoteAudit.Quantity := QuoteLine.Quantity;
        QuoteAudit."Landed Cost per Unit" := QuoteLine."Landed Cost per Unit";
        QuoteAudit."Proposed Sell Price" := QuoteLine."Proposed Sell Price";
        QuoteAudit."Target Gross Margin %" := QuoteLine."Target Gross Margin %";
        QuoteAudit."Calculated GP %" := QuoteLine."Calculated GP %";
        QuoteAudit."Guardrail Status" := QuoteLine."Guardrail Status";
        QuoteAudit."Needs Approval" := QuoteLine."Needs Approval";
        QuoteAudit."Guardrail Approver" := QuoteLine."Guardrail Approver";
        QuoteAudit."Pricing Rule Entry No." := QuoteLine."Pricing Rule Entry No.";
        QuoteAudit."Policy Fixed Sell Price" := QuoteLine."Policy Fixed Sell Price";
        QuoteAudit."Event Note" := CopyStr(EventNote, 1, MaxStrLen(QuoteAudit."Event Note"));
        QuoteAudit."Previous Quantity" := PreviousLine.Quantity;
        QuoteAudit."Previous Landed Cost" := PreviousLine."Landed Cost per Unit";
        QuoteAudit."Previous Sell Price" := PreviousLine."Proposed Sell Price";
        QuoteAudit."Previous Target GM %" := PreviousLine."Target Gross Margin %";
        QuoteAudit."Previous Product No." := PreviousLine."Product No.";
        QuoteAudit."Previous BC Item No." := PreviousLine."BC Item No.";
        QuoteAudit."Previous UOM Code" := PreviousLine."UOM Code";
        QuoteAudit."Previous Guard Status" := PreviousLine."Guardrail Status";
        QuoteAudit.Insert(true);
    end;
}
