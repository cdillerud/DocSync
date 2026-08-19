codeunit 71002 "GPI Pack Quote Mgt"
{
    procedure InitializeLineFromProduct(var QuoteLine: Record "GPI Pack Quote Line")
    var
        Product: Record "GPI Pack Product";
    begin
        if QuoteLine."Product No." = '' then begin
            QuoteLine.Description := '';
            QuoteLine."BC Item No." := '';
            QuoteLine."UOM Code" := '';
            RecalculateLine(QuoteLine);
            exit;
        end;

        Product.Get(QuoteLine."Product No.");

        if Product.Style <> '' then
            QuoteLine.Description := CopyStr(Product.Style, 1, MaxStrLen(QuoteLine.Description))
        else
            QuoteLine.Description := CopyStr(Product."No.", 1, MaxStrLen(QuoteLine.Description));

        QuoteLine."BC Item No." := Product."BC Item No.";
        SetDefaultUOMFromItem(QuoteLine);
        RecalculateLine(QuoteLine);
    end;

    procedure InitializeLineFromCostWork(var QuoteLine: Record "GPI Pack Quote Line")
    var
        CostWork: Record "GPI Pack Cost Work";
    begin
        if QuoteLine."Cost Worksheet Entry No." = 0 then begin
            RecalculateLine(QuoteLine);
            exit;
        end;

        CostWork.Get(QuoteLine."Cost Worksheet Entry No.");

        if CostWork."Product No." <> '' then begin
            QuoteLine."Product No." := CostWork."Product No.";
            InitializeLineFromProduct(QuoteLine);
        end;

        if CostWork.Quantity > 0 then
            QuoteLine.Quantity := CostWork.Quantity;

        QuoteLine."Landed Cost per Unit" := CostWork."Landed Cost per Unit";
        QuoteLine."Target Gross Margin %" := CostWork."Target Gross Margin %";
        RecalculateLine(QuoteLine);
    end;

    procedure SetDefaultUOMFromItem(var QuoteLine: Record "GPI Pack Quote Line")
    var
        Item: Record Item;
    begin
        if QuoteLine."BC Item No." = '' then begin
            QuoteLine."UOM Code" := '';
            exit;
        end;

        Item.Get(QuoteLine."BC Item No.");
        QuoteLine."UOM Code" := Item."Base Unit of Measure";
    end;

    procedure RecalculateLine(var QuoteLine: Record "GPI Pack Quote Line")
    var
        MarginFactor: Decimal;
    begin
        QuoteLine."Suggested Sell Price" := 0;
        QuoteLine."Calculated GP %" := 0;
        QuoteLine."Extended Landed Cost" := 0;
        QuoteLine."Extended Sell" := 0;
        QuoteLine."Gross Profit Total" := 0;

        if QuoteLine.Quantity > 0 then begin
            QuoteLine."Extended Landed Cost" := Round(QuoteLine."Landed Cost per Unit" * QuoteLine.Quantity, 0.01, '=');
            QuoteLine."Extended Sell" := Round(QuoteLine."Proposed Sell Price" * QuoteLine.Quantity, 0.01, '=');
            QuoteLine."Gross Profit Total" := Round((QuoteLine."Proposed Sell Price" - QuoteLine."Landed Cost per Unit") * QuoteLine.Quantity, 0.01, '=');
        end;

        if QuoteLine."Proposed Sell Price" > 0 then
            QuoteLine."Calculated GP %" := Round(
                ((QuoteLine."Proposed Sell Price" - QuoteLine."Landed Cost per Unit") / QuoteLine."Proposed Sell Price") * 100,
                0.00001,
                '=');

        if (QuoteLine."Landed Cost per Unit" > 0) and (QuoteLine."Target Gross Margin %" < 100) then begin
            MarginFactor := 1 - (QuoteLine."Target Gross Margin %" / 100);
            if MarginFactor > 0 then
                QuoteLine."Suggested Sell Price" := Round(QuoteLine."Landed Cost per Unit" / MarginFactor, 0.00001, '=');
        end;

        InvalidateLine(QuoteLine);
    end;

    procedure InvalidateLine(var QuoteLine: Record "GPI Pack Quote Line")
    var
        QuoteHeader: Record "GPI Pack Quote";
    begin
        QuoteLine."Guardrail Status" := "GPI Quote Guard Stat"::"Not Evaluated";
        QuoteLine."Guardrail Message" := '';
        QuoteLine."Guardrail Approver" := '';
        QuoteLine."Pricing Rule Entry No." := 0;
        QuoteLine."Policy Fixed Sell Price" := 0;
        QuoteLine."Needs Approval" := false;
        QuoteLine."Evaluated At" := 0DT;
        QuoteLine."Evaluated By" := '';

        if (QuoteLine."Quote Entry No." <> 0) and QuoteHeader.Get(QuoteLine."Quote Entry No.") then
            if QuoteHeader.Status <> "GPI Pack Quote Stat"::Draft then begin
                QuoteHeader.Status := "GPI Pack Quote Stat"::Draft;
                QuoteHeader."Last Evaluated At" := 0DT;
                QuoteHeader."Last Evaluated By" := '';
                QuoteHeader.Modify(false);
            end;
    end;

    procedure EvaluateLine(var QuoteLine: Record "GPI Pack Quote Line")
    var
        QuoteHeader: Record "GPI Pack Quote";
        PricingGuard: Record "GPI Pricing Guard";
        AsOfDate: Date;
        RuleSpec: Integer;
        FixedSpec: Integer;
        SpecialSpec: Integer;
        FixedFound: Boolean;
        FixedConflict: Boolean;
        SpecialFound: Boolean;
        FixedPrice: Decimal;
        FixedRuleEntryNo: Integer;
        SpecialRuleEntryNo: Integer;
        FixedApprover: Text[100];
        SpecialApprover: Text[100];
        CombinedApprover: Text[100];
    begin
        RecalculateLine(QuoteLine);

        if not QuoteHeader.Get(QuoteLine."Quote Entry No.") then begin
            SetEvaluation(QuoteLine, "GPI Quote Guard Stat"::"Approval Required", true, 'Quote header was not found.', '', 0);
            exit;
        end;

        if QuoteHeader."Customer No." = '' then begin
            SetEvaluation(QuoteLine, "GPI Quote Guard Stat"::"Approval Required", true, 'Customer No. is required before pricing can be evaluated.', '', 0);
            exit;
        end;

        if QuoteLine.Quantity <= 0 then begin
            SetEvaluation(QuoteLine, "GPI Quote Guard Stat"::"Approval Required", true, 'Quantity must be greater than zero.', '', 0);
            exit;
        end;

        if QuoteLine."Proposed Sell Price" <= 0 then begin
            SetEvaluation(QuoteLine, "GPI Quote Guard Stat"::"Approval Required", true, 'Proposed Sell Price must be greater than zero.', '', 0);
            exit;
        end;

        if QuoteLine."Landed Cost per Unit" <= 0 then begin
            SetEvaluation(QuoteLine, "GPI Quote Guard Stat"::"Missing Cost", true, 'Landed Cost per Unit is required before the quote can be released.', '', 0);
            exit;
        end;

        AsOfDate := QuoteHeader."Quote Date";
        if AsOfDate = 0D then
            AsOfDate := WorkDate();

        PricingGuard.SetRange(Enabled, true);
        if PricingGuard.FindSet() then
            repeat
                if RuleApplies(PricingGuard, QuoteHeader."Customer No.", QuoteLine."BC Item No.", AsOfDate) then begin
                    RuleSpec := RuleSpecificity(PricingGuard);

                    case PricingGuard."Rule Type" of
                        "GPI Price Rule Type"::"Fixed Price":
                            begin
                                if RuleSpec > FixedSpec then begin
                                    FixedSpec := RuleSpec;
                                    FixedFound := true;
                                    FixedConflict := false;
                                    FixedPrice := PricingGuard."Locked Sell Price";
                                    FixedRuleEntryNo := PricingGuard."Entry No.";
                                    FixedApprover := PricingGuard.Approver;
                                end else
                                    if RuleSpec = FixedSpec then begin
                                        if not FixedFound then begin
                                            FixedFound := true;
                                            FixedPrice := PricingGuard."Locked Sell Price";
                                            FixedRuleEntryNo := PricingGuard."Entry No.";
                                            FixedApprover := PricingGuard.Approver;
                                        end else begin
                                            if Abs(PricingGuard."Locked Sell Price" - FixedPrice) > 0.0001 then
                                                FixedConflict := true;
                                            AddApprover(FixedApprover, PricingGuard.Approver);
                                        end;
                                    end;
                            end;
                        "GPI Price Rule Type"::"Special Pricing":
                            begin
                                if RuleSpec > SpecialSpec then begin
                                    SpecialSpec := RuleSpec;
                                    SpecialFound := true;
                                    SpecialRuleEntryNo := PricingGuard."Entry No.";
                                    SpecialApprover := PricingGuard.Approver;
                                end else
                                    if RuleSpec = SpecialSpec then begin
                                        SpecialFound := true;
                                        AddApprover(SpecialApprover, PricingGuard.Approver);
                                    end;
                            end;
                    end;
                end;
            until PricingGuard.Next() = 0;

        if FixedFound then begin
            QuoteLine."Policy Fixed Sell Price" := FixedPrice;
            CombinedApprover := FixedApprover;
            AddApprover(CombinedApprover, SpecialApprover);

            if FixedConflict then begin
                SetEvaluation(
                    QuoteLine,
                    "GPI Quote Guard Stat"::"Fixed Price Conflict",
                    true,
                    'Multiple equally specific Fixed Price guardrails disagree. Resolve the pricing rules before approval.',
                    CombinedApprover,
                    FixedRuleEntryNo);
                exit;
            end;

            if Abs(QuoteLine."Proposed Sell Price" - FixedPrice) > 0.0001 then begin
                SetEvaluation(
                    QuoteLine,
                    "GPI Quote Guard Stat"::"Fixed Price Conflict",
                    true,
                    CopyStr(StrSubstNo('Proposed sell %1 conflicts with protected fixed price %2.', QuoteLine."Proposed Sell Price", FixedPrice), 1, MaxStrLen(QuoteLine."Guardrail Message")),
                    CombinedApprover,
                    FixedRuleEntryNo);
                exit;
            end;
        end;

        if SpecialFound then begin
            CombinedApprover := SpecialApprover;
            AddApprover(CombinedApprover, FixedApprover);
            SetEvaluation(
                QuoteLine,
                "GPI Quote Guard Stat"::"Special Pricing",
                true,
                'Active Special Pricing protects this customer/item. Review pricing with the configured approver instead of inferring a replacement price.',
                CombinedApprover,
                SpecialRuleEntryNo);
            exit;
        end;

        if (QuoteLine."Target Gross Margin %" > 0) and
           (QuoteLine."Calculated GP %" + 0.00001 < QuoteLine."Target Gross Margin %")
        then begin
            SetEvaluation(
                QuoteLine,
                "GPI Quote Guard Stat"::"Below Target Margin",
                true,
                CopyStr(StrSubstNo('Calculated GP %1%% is below target GP %2%%.', QuoteLine."Calculated GP %", QuoteLine."Target Gross Margin %"), 1, MaxStrLen(QuoteLine."Guardrail Message")),
                '',
                0);
            exit;
        end;

        if FixedFound then begin
            SetEvaluation(
                QuoteLine,
                "GPI Quote Guard Stat"::"Fixed Price Match",
                false,
                'Proposed sell price matches the active Fixed Price guardrail.',
                FixedApprover,
                FixedRuleEntryNo);
            exit;
        end;

        SetEvaluation(
            QuoteLine,
            "GPI Quote Guard Stat"::"Within Policy",
            false,
            'No active protected pricing conflict was found and the proposed margin is at or above target.',
            '',
            0);
    end;

    procedure EvaluateQuote(var QuoteHeader: Record "GPI Pack Quote")
    var
        QuoteLine: Record "GPI Pack Quote Line";
    begin
        QuoteHeader.TestField("Customer No.");

        QuoteLine.SetRange("Quote Entry No.", QuoteHeader."Entry No.");
        if not QuoteLine.FindSet(true) then
            Error('Add at least one quote line before evaluating the quote.');

        repeat
            EvaluateLine(QuoteLine);
            QuoteLine.Modify(false);
        until QuoteLine.Next() = 0;

        QuoteHeader."Last Evaluated At" := CurrentDateTime();
        QuoteHeader."Last Evaluated By" := CopyStr(UserId(), 1, MaxStrLen(QuoteHeader."Last Evaluated By"));
        QuoteHeader.Modify(false);
    end;

    procedure SetReadyForReview(var QuoteHeader: Record "GPI Pack Quote")
    var
        QuoteLine: Record "GPI Pack Quote Line";
    begin
        EvaluateQuote(QuoteHeader);

        QuoteLine.SetRange("Quote Entry No.", QuoteHeader."Entry No.");
        if QuoteLine.FindSet() then
            repeat
                case QuoteLine."Guardrail Status" of
                    "GPI Quote Guard Stat"::"Not Evaluated",
                    "GPI Quote Guard Stat"::"Approval Required",
                    "GPI Quote Guard Stat"::"Missing Cost":
                        Error('Line %1 is incomplete: %2', QuoteLine."Line No.", QuoteLine."Guardrail Message");
                end;
            until QuoteLine.Next() = 0;

        QuoteHeader.Status := "GPI Pack Quote Stat"::Ready;
        QuoteHeader.Modify(true);
    end;

    procedure ReopenQuote(var QuoteHeader: Record "GPI Pack Quote")
    begin
        QuoteHeader.Status := "GPI Pack Quote Stat"::Draft;
        QuoteHeader.Modify(true);
    end;

    local procedure RuleApplies(PricingGuard: Record "GPI Pricing Guard"; CustomerNo: Code[20]; ItemNo: Code[20]; AsOfDate: Date): Boolean
    begin
        if not PricingGuard.Enabled then
            exit(false);

        if (PricingGuard."Customer No." <> '') and (PricingGuard."Customer No." <> CustomerNo) then
            exit(false);

        if (PricingGuard."Item No." <> '') and (PricingGuard."Item No." <> ItemNo) then
            exit(false);

        if (PricingGuard."Effective From" <> 0D) and (AsOfDate < PricingGuard."Effective From") then
            exit(false);

        if (PricingGuard."Effective To" <> 0D) and (AsOfDate > PricingGuard."Effective To") then
            exit(false);

        exit(true);
    end;

    local procedure RuleSpecificity(PricingGuard: Record "GPI Pricing Guard"): Integer
    var
        Specificity: Integer;
    begin
        if PricingGuard."Customer No." <> '' then
            Specificity := Specificity + 1;
        if PricingGuard."Item No." <> '' then
            Specificity := Specificity + 1;
        exit(Specificity);
    end;

    local procedure SetEvaluation(var QuoteLine: Record "GPI Pack Quote Line"; GuardStatus: Enum "GPI Quote Guard Stat"; NeedsApproval: Boolean; MessageText: Text; ApproverText: Text; RuleEntryNo: Integer)
    begin
        QuoteLine."Guardrail Status" := GuardStatus;
        QuoteLine."Needs Approval" := NeedsApproval;
        QuoteLine."Guardrail Message" := CopyStr(MessageText, 1, MaxStrLen(QuoteLine."Guardrail Message"));
        QuoteLine."Guardrail Approver" := CopyStr(ApproverText, 1, MaxStrLen(QuoteLine."Guardrail Approver"));
        QuoteLine."Pricing Rule Entry No." := RuleEntryNo;
        QuoteLine."Evaluated At" := CurrentDateTime();
        QuoteLine."Evaluated By" := CopyStr(UserId(), 1, MaxStrLen(QuoteLine."Evaluated By"));
    end;

    local procedure AddApprover(var Approvers: Text[100]; NewApprover: Text[100])
    begin
        if NewApprover = '' then
            exit;

        if Approvers = '' then begin
            Approvers := NewApprover;
            exit;
        end;

        if StrPos(',' + Approvers + ',', ',' + NewApprover + ',') > 0 then
            exit;

        Approvers := CopyStr(Approvers + ', ' + NewApprover, 1, MaxStrLen(Approvers));
    end;
}
