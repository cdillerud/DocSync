codeunit 70707 "GPI Routing Resolver Tests"
{
    Subtype = Test;

    [Test]
    procedure CustomerRulesApplyInPriorityOrder()
    var
        RoutingRule: Record "GPI Document Routing Rule" temporary;
        Resolver: Codeunit "GPI Routing Rule Resolver";
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedEntries: Text[250];
        ReplaceApplied: Boolean;
    begin
        AddCustomerRule(RoutingRule, 20, 200, 'C100', '', false, 'second@example.com', '', '', 0D, 0D);
        AddCustomerRule(RoutingRule, 10, 100, 'C100', '', false, 'first@example.com', '', '', 0D, 0D);

        AssertTrue(
            Resolver.ApplyCustomerRuleSet(
                RoutingRule,
                Enum::"GPI Delivery Document Type"::"Customer Open Order Status",
                'C100',
                '',
                true,
                DMY2Date(19, 6, 2026),
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedEntries,
                ReplaceApplied),
            'The matching customer rules were not applied.');

        AssertEqualText('first@example.com; second@example.com', Phase2EmailMgt.JoinRecipients(ToRecipients), 'Customer rules did not follow ascending priority.');
        AssertEqualText('10,20', AppliedEntries, 'Applied routing entries were not recorded in priority order.');
        AssertFalse(ReplaceApplied, 'Add-only rules should not set ReplaceApplied.');
    end;

    [Test]
    procedure ReplaceRuleClearsEarlierAndDefaultRecipients()
    var
        RoutingRule: Record "GPI Document Routing Rule" temporary;
        Resolver: Codeunit "GPI Routing Rule Resolver";
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedEntries: Text[250];
        ReplaceApplied: Boolean;
    begin
        ToRecipients.Add('default@example.com');
        CCRecipients.Add('defaultcc@example.com');
        AddCustomerRule(RoutingRule, 10, 50, 'C200', '', false, 'early@example.com', '', '', 0D, 0D);
        AddCustomerRule(RoutingRule, 20, 100, 'C200', '', true, 'replace@example.com', 'replacecc@example.com', '', 0D, 0D);
        AddCustomerRule(RoutingRule, 30, 150, 'C200', '', false, 'late@example.com', '', '', 0D, 0D);

        Resolver.ApplyCustomerRuleSet(
            RoutingRule,
            Enum::"GPI Delivery Document Type"::"Customer Open Order Status",
            'C200',
            '',
            true,
            DMY2Date(19, 6, 2026),
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedEntries,
            ReplaceApplied);

        AssertEqualText('replace@example.com; late@example.com', Phase2EmailMgt.JoinRecipients(ToRecipients), 'Replace did not clear earlier To recipients.');
        AssertEqualText('replacecc@example.com', Phase2EmailMgt.JoinRecipients(CCRecipients), 'Replace did not clear earlier CC recipients.');
        AssertTrue(ReplaceApplied, 'A Replace rule must set ReplaceApplied.');
        AssertEqualText('10,20,30', AppliedEntries, 'All applied rules should remain in the audit sequence.');
    end;

    [Test]
    procedure InactiveRulesAreIgnored()
    var
        RoutingRule: Record "GPI Document Routing Rule" temporary;
        Resolver: Codeunit "GPI Routing Rule Resolver";
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedEntries: Text[250];
        ReplaceApplied: Boolean;
        EvaluationDate: Date;
    begin
        EvaluationDate := DMY2Date(19, 6, 2026);
        AddCustomerRule(RoutingRule, 10, 10, 'C300', '', false, 'expired@example.com', '', '', DMY2Date(1, 1, 2026), DMY2Date(18, 6, 2026));
        AddCustomerRule(RoutingRule, 20, 20, 'C300', '', false, 'future@example.com', '', '', DMY2Date(20, 6, 2026), 0D);
        AddCustomerRule(RoutingRule, 30, 30, 'C300', '', false, 'active@example.com', '', '', DMY2Date(1, 6, 2026), DMY2Date(30, 6, 2026));

        Resolver.ApplyCustomerRuleSet(
            RoutingRule,
            Enum::"GPI Delivery Document Type"::"Customer Open Order Status",
            'C300',
            '',
            true,
            EvaluationDate,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedEntries,
            ReplaceApplied);

        AssertEqualText('active@example.com', Phase2EmailMgt.JoinRecipients(ToRecipients), 'Expired or future routing rules were applied.');
        AssertEqualText('30', AppliedEntries, 'Only the active routing rule should be recorded.');
    end;

    [Test]
    procedure SpecificAndGenericCustomerScopesRemainSeparate()
    var
        RoutingRule: Record "GPI Document Routing Rule" temporary;
        Resolver: Codeunit "GPI Routing Rule Resolver";
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedEntries: Text[250];
        ReplaceApplied: Boolean;
    begin
        AddCustomerRule(RoutingRule, 10, 10, '', '', false, 'generic@example.com', '', '', 0D, 0D);
        AddCustomerRule(RoutingRule, 20, 20, 'C400', '', false, 'specific@example.com', '', '', 0D, 0D);

        Resolver.ApplyCustomerRuleSet(
            RoutingRule,
            Enum::"GPI Delivery Document Type"::"Customer Open Order Status",
            'C400',
            '',
            true,
            DMY2Date(19, 6, 2026),
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedEntries,
            ReplaceApplied);

        AssertEqualText('specific@example.com', Phase2EmailMgt.JoinRecipients(ToRecipients), 'A generic rule leaked into the specific-customer pass.');
        AssertEqualText('20', AppliedEntries, 'The specific-customer pass recorded the wrong rule.');

        Clear(ToRecipients);
        Clear(CCRecipients);
        Clear(BCCRecipients);
        Clear(AppliedEntries);
        Clear(ReplaceApplied);
        RoutingRule.Reset();

        Resolver.ApplyCustomerRuleSet(
            RoutingRule,
            Enum::"GPI Delivery Document Type"::"Customer Open Order Status",
            'C400',
            '',
            false,
            DMY2Date(19, 6, 2026),
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedEntries,
            ReplaceApplied);

        AssertEqualText('generic@example.com', Phase2EmailMgt.JoinRecipients(ToRecipients), 'The generic-customer pass did not apply the generic rule.');
        AssertEqualText('10', AppliedEntries, 'The generic-customer pass recorded the wrong rule.');
    end;

    [Test]
    procedure CustomerRuleHonorsOptionalLocationConstraint()
    var
        RoutingRule: Record "GPI Document Routing Rule" temporary;
        Resolver: Codeunit "GPI Routing Rule Resolver";
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedEntries: Text[250];
        ReplaceApplied: Boolean;
    begin
        AddCustomerRule(RoutingRule, 10, 10, 'C500', 'WRONG', false, 'wrong@example.com', '', '', 0D, 0D);
        AddCustomerRule(RoutingRule, 20, 20, 'C500', '', false, 'alllocations@example.com', '', '', 0D, 0D);
        AddCustomerRule(RoutingRule, 30, 30, 'C500', 'MAIN', false, 'main@example.com', '', '', 0D, 0D);

        Resolver.ApplyCustomerRuleSet(
            RoutingRule,
            Enum::"GPI Delivery Document Type"::"Customer Open Order Status",
            'C500',
            'MAIN',
            true,
            DMY2Date(19, 6, 2026),
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedEntries,
            ReplaceApplied);

        AssertEqualText('alllocations@example.com; main@example.com', Phase2EmailMgt.JoinRecipients(ToRecipients), 'Customer location constraints were not respected.');
        AssertEqualText('20,30', AppliedEntries, 'The wrong-location rule should not be audited as applied.');
    end;

    [Test]
    procedure VendorRulesIgnoreCustomerRules()
    var
        RoutingRule: Record "GPI Document Routing Rule" temporary;
        Resolver: Codeunit "GPI Routing Rule Resolver";
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedEntries: Text[250];
        ReplaceApplied: Boolean;
    begin
        AddVendorRule(RoutingRule, 10, 10, 'V100', false, 'vendor@example.com');
        AddCustomerRule(RoutingRule, 20, 20, 'C100', '', false, 'customer@example.com', '', '', 0D, 0D);

        Resolver.ApplyVendorRuleSet(
            RoutingRule,
            Enum::"GPI Delivery Document Type"::"Purchase Return Order",
            'V100',
            '',
            true,
            DMY2Date(19, 6, 2026),
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedEntries,
            ReplaceApplied);

        AssertEqualText('vendor@example.com', Phase2EmailMgt.JoinRecipients(ToRecipients), 'A customer rule leaked into the vendor pass.');
        AssertEqualText('10', AppliedEntries, 'The vendor pass recorded the wrong rule.');
    end;

    [Test]
    procedure LocationRulesSeparateSpecificAndGenericScopes()
    var
        RoutingRule: Record "GPI Document Routing Rule" temporary;
        Resolver: Codeunit "GPI Routing Rule Resolver";
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedEntries: Text[250];
        ReplaceApplied: Boolean;
    begin
        AddLocationRule(RoutingRule, 10, 10, '', 'genericwarehouse@example.com');
        AddLocationRule(RoutingRule, 20, 20, 'MAIN', 'mainwarehouse@example.com');

        Resolver.ApplyLocationRuleSet(
            RoutingRule,
            Enum::"GPI Delivery Document Type"::"Transfer Pick List",
            'MAIN',
            true,
            DMY2Date(19, 6, 2026),
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedEntries,
            ReplaceApplied);

        AssertEqualText('mainwarehouse@example.com', Phase2EmailMgt.JoinRecipients(ToRecipients), 'A generic location rule leaked into the specific-location pass.');
        AssertEqualText('20', AppliedEntries, 'The specific-location pass recorded the wrong rule.');
    end;

    local procedure AddCustomerRule(var RoutingRule: Record "GPI Document Routing Rule" temporary; EntryNo: Integer; Priority: Integer; CustomerNo: Code[20]; LocationCode: Code[10]; ReplaceRecipients: Boolean; ToAddresses: Text; CCAddresses: Text; BCCAddresses: Text; StartDate: Date; EndDate: Date)
    begin
        RoutingRule.Init();
        RoutingRule."Entry No." := EntryNo;
        RoutingRule.Enabled := true;
        RoutingRule.Priority := Priority;
        RoutingRule."Delivery Document Type" := Enum::"GPI Delivery Document Type"::"Customer Open Order Status";
        RoutingRule."Customer No." := CustomerNo;
        RoutingRule."Location Code" := LocationCode;
        if ReplaceRecipients then
            RoutingRule."Recipient Action" := RoutingRule."Recipient Action"::Replace
        else
            RoutingRule."Recipient Action" := RoutingRule."Recipient Action"::Add;
        RoutingRule."To Addresses" := ToAddresses;
        RoutingRule."CC Addresses" := CCAddresses;
        RoutingRule."BCC Addresses" := BCCAddresses;
        RoutingRule."Effective Start Date" := StartDate;
        RoutingRule."Effective End Date" := EndDate;
        RoutingRule.Insert();
    end;

    local procedure AddVendorRule(var RoutingRule: Record "GPI Document Routing Rule" temporary; EntryNo: Integer; Priority: Integer; VendorNo: Code[20]; ReplaceRecipients: Boolean; ToAddresses: Text)
    begin
        RoutingRule.Init();
        RoutingRule."Entry No." := EntryNo;
        RoutingRule.Enabled := true;
        RoutingRule.Priority := Priority;
        RoutingRule."Delivery Document Type" := Enum::"GPI Delivery Document Type"::"Purchase Return Order";
        RoutingRule."Vendor No." := VendorNo;
        if ReplaceRecipients then
            RoutingRule."Recipient Action" := RoutingRule."Recipient Action"::Replace
        else
            RoutingRule."Recipient Action" := RoutingRule."Recipient Action"::Add;
        RoutingRule."To Addresses" := ToAddresses;
        RoutingRule.Insert();
    end;

    local procedure AddLocationRule(var RoutingRule: Record "GPI Document Routing Rule" temporary; EntryNo: Integer; Priority: Integer; LocationCode: Code[10]; ToAddresses: Text)
    begin
        RoutingRule.Init();
        RoutingRule."Entry No." := EntryNo;
        RoutingRule.Enabled := true;
        RoutingRule.Priority := Priority;
        RoutingRule."Delivery Document Type" := Enum::"GPI Delivery Document Type"::"Transfer Pick List";
        RoutingRule."Location Code" := LocationCode;
        RoutingRule."Recipient Action" := RoutingRule."Recipient Action"::Add;
        RoutingRule."To Addresses" := ToAddresses;
        RoutingRule.Insert();
    end;

    local procedure AssertTrue(Condition: Boolean; FailureMessage: Text)
    begin
        if not Condition then
            Error('%1', FailureMessage);
    end;

    local procedure AssertFalse(Condition: Boolean; FailureMessage: Text)
    begin
        if Condition then
            Error('%1', FailureMessage);
    end;

    local procedure AssertEqualText(Expected: Text; Actual: Text; FailureMessage: Text)
    begin
        if Expected <> Actual then
            Error('%1 Expected "%2" but received "%3".', FailureMessage, Expected, Actual);
    end;
}
