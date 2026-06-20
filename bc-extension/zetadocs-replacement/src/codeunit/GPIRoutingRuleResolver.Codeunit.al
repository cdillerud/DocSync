codeunit 70590 "GPI Routing Rule Resolver"
{
    procedure ApplyCustomerRules(DeliveryDocumentType: Enum "GPI Delivery Document Type"; CustomerNo: Code[20]; LocationCode: Code[10]; SpecificCustomerOnly: Boolean; EvaluationDate: Date; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RoutingRule: Record "GPI Document Routing Rule";
    begin
        exit(ApplyCustomerRuleSet(
            RoutingRule,
            DeliveryDocumentType,
            CustomerNo,
            LocationCode,
            SpecificCustomerOnly,
            EvaluationDate,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries,
            ReplaceApplied));
    end;

    procedure ApplyVendorRules(DeliveryDocumentType: Enum "GPI Delivery Document Type"; VendorNo: Code[20]; LocationCode: Code[10]; SpecificVendorOnly: Boolean; EvaluationDate: Date; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RoutingRule: Record "GPI Document Routing Rule";
    begin
        exit(ApplyVendorRuleSet(
            RoutingRule,
            DeliveryDocumentType,
            VendorNo,
            LocationCode,
            SpecificVendorOnly,
            EvaluationDate,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries,
            ReplaceApplied));
    end;

    procedure ApplyLocationRules(DeliveryDocumentType: Enum "GPI Delivery Document Type"; LocationCode: Code[10]; SpecificLocationOnly: Boolean; EvaluationDate: Date; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RoutingRule: Record "GPI Document Routing Rule";
    begin
        exit(ApplyLocationRuleSet(
            RoutingRule,
            DeliveryDocumentType,
            LocationCode,
            SpecificLocationOnly,
            EvaluationDate,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries,
            ReplaceApplied));
    end;

    procedure ApplyCustomerRuleSet(var RoutingRule: Record "GPI Document Routing Rule"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; CustomerNo: Code[20]; LocationCode: Code[10]; SpecificCustomerOnly: Boolean; EvaluationDate: Date; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RuleApplied: Boolean;
    begin
        PrepareRuleSet(RoutingRule, DeliveryDocumentType);
        if not RoutingRule.FindSet() then
            exit(false);

        repeat
            if CustomerRuleMatches(RoutingRule, CustomerNo, LocationCode, SpecificCustomerOnly) and
               RuleIsActive(RoutingRule, EvaluationDate)
            then begin
                ApplyMatchedRule(
                    RoutingRule,
                    ToRecipients,
                    CCRecipients,
                    BCCRecipients,
                    AppliedRuleEntries,
                    ReplaceApplied);
                RuleApplied := true;
            end;
        until RoutingRule.Next() = 0;

        exit(RuleApplied);
    end;

    procedure ApplyVendorRuleSet(var RoutingRule: Record "GPI Document Routing Rule"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; VendorNo: Code[20]; LocationCode: Code[10]; SpecificVendorOnly: Boolean; EvaluationDate: Date; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RuleApplied: Boolean;
    begin
        PrepareRuleSet(RoutingRule, DeliveryDocumentType);
        if not RoutingRule.FindSet() then
            exit(false);

        repeat
            if VendorRuleMatches(RoutingRule, VendorNo, LocationCode, SpecificVendorOnly) and
               RuleIsActive(RoutingRule, EvaluationDate)
            then begin
                ApplyMatchedRule(
                    RoutingRule,
                    ToRecipients,
                    CCRecipients,
                    BCCRecipients,
                    AppliedRuleEntries,
                    ReplaceApplied);
                RuleApplied := true;
            end;
        until RoutingRule.Next() = 0;

        exit(RuleApplied);
    end;

    procedure ApplyLocationRuleSet(var RoutingRule: Record "GPI Document Routing Rule"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; LocationCode: Code[10]; SpecificLocationOnly: Boolean; EvaluationDate: Date; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RuleApplied: Boolean;
    begin
        PrepareRuleSet(RoutingRule, DeliveryDocumentType);
        if not RoutingRule.FindSet() then
            exit(false);

        repeat
            if LocationRuleMatches(RoutingRule, LocationCode, SpecificLocationOnly) and
               RuleIsActive(RoutingRule, EvaluationDate)
            then begin
                ApplyMatchedRule(
                    RoutingRule,
                    ToRecipients,
                    CCRecipients,
                    BCCRecipients,
                    AppliedRuleEntries,
                    ReplaceApplied);
                RuleApplied := true;
            end;
        until RoutingRule.Next() = 0;

        exit(RuleApplied);
    end;

    local procedure PrepareRuleSet(var RoutingRule: Record "GPI Document Routing Rule"; DeliveryDocumentType: Enum "GPI Delivery Document Type")
    begin
        RoutingRule.SetCurrentKey(Enabled, "Delivery Document Type", Priority, "Entry No.");
        RoutingRule.Ascending(true);
        RoutingRule.SetRange(Enabled, true);
        RoutingRule.SetRange("Delivery Document Type", DeliveryDocumentType);
    end;

    local procedure CustomerRuleMatches(RoutingRule: Record "GPI Document Routing Rule"; CustomerNo: Code[20]; LocationCode: Code[10]; SpecificCustomerOnly: Boolean): Boolean
    begin
        if RoutingRule."Vendor No." <> '' then
            exit(false);

        if SpecificCustomerOnly then begin
            if RoutingRule."Customer No." <> CustomerNo then
                exit(false);
        end else
            if RoutingRule."Customer No." <> '' then
                exit(false);

        if (RoutingRule."Location Code" <> '') and
           (RoutingRule."Location Code" <> LocationCode)
        then
            exit(false);

        exit(true);
    end;

    local procedure VendorRuleMatches(RoutingRule: Record "GPI Document Routing Rule"; VendorNo: Code[20]; LocationCode: Code[10]; SpecificVendorOnly: Boolean): Boolean
    begin
        if RoutingRule."Customer No." <> '' then
            exit(false);

        if SpecificVendorOnly then begin
            if RoutingRule."Vendor No." <> VendorNo then
                exit(false);
        end else
            if RoutingRule."Vendor No." <> '' then
                exit(false);

        if (RoutingRule."Location Code" <> '') and
           (RoutingRule."Location Code" <> LocationCode)
        then
            exit(false);

        exit(true);
    end;

    local procedure LocationRuleMatches(RoutingRule: Record "GPI Document Routing Rule"; LocationCode: Code[10]; SpecificLocationOnly: Boolean): Boolean
    begin
        if (RoutingRule."Customer No." <> '') or
           (RoutingRule."Vendor No." <> '')
        then
            exit(false);

        if SpecificLocationOnly then
            exit(RoutingRule."Location Code" = LocationCode);

        exit(RoutingRule."Location Code" = '');
    end;

    local procedure RuleIsActive(RoutingRule: Record "GPI Document Routing Rule"; EvaluationDate: Date): Boolean
    begin
        if EvaluationDate = 0D then
            EvaluationDate := Today;

        if (RoutingRule."Effective Start Date" <> 0D) and
           (RoutingRule."Effective Start Date" > EvaluationDate)
        then
            exit(false);

        if (RoutingRule."Effective End Date" <> 0D) and
           (RoutingRule."Effective End Date" < EvaluationDate)
        then
            exit(false);

        exit(true);
    end;

    local procedure ApplyMatchedRule(RoutingRule: Record "GPI Document Routing Rule"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250]; var ReplaceApplied: Boolean)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
    begin
        if RoutingRule."Recipient Action" = RoutingRule."Recipient Action"::Replace then begin
            Clear(ToRecipients);
            Clear(CCRecipients);
            Clear(BCCRecipients);
            ReplaceApplied := true;
        end;

        Phase2EmailMgt.AddRecipientsFromText(ToRecipients, RoutingRule."To Addresses");
        Phase2EmailMgt.AddRecipientsFromText(CCRecipients, RoutingRule."CC Addresses");
        Phase2EmailMgt.AddRecipientsFromText(BCCRecipients, RoutingRule."BCC Addresses");
        AppendRuleEntry(AppliedRuleEntries, RoutingRule."Entry No.");
    end;

    local procedure AppendRuleEntry(var AppliedRuleEntries: Text[250]; EntryNo: Integer)
    begin
        if AppliedRuleEntries = '' then
            AppliedRuleEntries := CopyStr(Format(EntryNo), 1, MaxStrLen(AppliedRuleEntries))
        else
            AppliedRuleEntries := CopyStr(
                AppliedRuleEntries + ',' + Format(EntryNo),
                1,
                MaxStrLen(AppliedRuleEntries));
    end;
}
