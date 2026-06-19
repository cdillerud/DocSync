codeunit 70700 "GPI Recipient Tests"
{
    Subtype = Test;

    [Test]
    procedure AddRecipientsParsesCommaAndSemicolonLists()
    var
        EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        Recipients: List of [Text];
    begin
        EmailMgt.AddRecipientsFromText(
            Recipients,
            'first@example.com; second@example.com, FIRST@example.com; invalid');

        AssertEqualInteger(2, Recipients.Count(), 'Recipient parsing should keep two unique valid addresses.');
        AssertTrue(EmailMgt.ContainsAddress(Recipients, 'first@example.com'), 'The first address was not added.');
        AssertTrue(EmailMgt.ContainsAddress(Recipients, 'SECOND@example.com'), 'Address matching should be case-insensitive.');
    end;

    [Test]
    procedure NormalizeRecipientsRemovesSenderAndCrossListDuplicates()
    var
        EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
    begin
        ToRecipients.Add('customer@example.com');
        ToRecipients.Add('sender@example.com');
        CCRecipients.Add('CUSTOMER@example.com');
        CCRecipients.Add('sales@example.com');
        CCRecipients.Add('sender@example.com');
        BCCRecipients.Add('sales@example.com');
        BCCRecipients.Add('audit@example.com');
        BCCRecipients.Add('SENDER@example.com');

        EmailMgt.NormalizeRecipientLists(
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            'sender@example.com');

        AssertEqualInteger(1, ToRecipients.Count(), 'Only the customer should remain in To.');
        AssertEqualInteger(1, CCRecipients.Count(), 'Only the sales recipient should remain in CC.');
        AssertEqualInteger(1, BCCRecipients.Count(), 'Only the audit recipient should remain in BCC.');
        AssertTrue(EmailMgt.ContainsAddress(ToRecipients, 'customer@example.com'), 'Customer recipient missing from To.');
        AssertTrue(EmailMgt.ContainsAddress(CCRecipients, 'sales@example.com'), 'Sales recipient missing from CC.');
        AssertTrue(EmailMgt.ContainsAddress(BCCRecipients, 'audit@example.com'), 'Audit recipient missing from BCC.');
        AssertFalse(EmailMgt.ContainsAddress(ToRecipients, 'sender@example.com'), 'Sender must not remain in To.');
        AssertFalse(EmailMgt.ContainsAddress(CCRecipients, 'sender@example.com'), 'Sender must not remain in CC.');
        AssertFalse(EmailMgt.ContainsAddress(BCCRecipients, 'sender@example.com'), 'Sender must not remain in BCC.');
    end;

    [Test]
    procedure JoinRecipientsUsesSemicolonSeparator()
    var
        EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        Recipients: List of [Text];
        JoinedRecipients: Text;
    begin
        Recipients.Add('first@example.com');
        Recipients.Add('second@example.com');

        JoinedRecipients := EmailMgt.JoinRecipients(Recipients);

        AssertEqualText(
            'first@example.com; second@example.com',
            JoinedRecipients,
            'Joined recipients were not formatted as expected.');
    end;

    [Test]
    procedure AddUniqueRecipientExceptSkipsExcludedAddress()
    var
        EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        Recipients: List of [Text];
    begin
        EmailMgt.AddUniqueRecipientExcept(
            Recipients,
            'SENDER@example.com',
            'sender@example.com');

        AssertEqualInteger(0, Recipients.Count(), 'The excluded sender address should not be added.');
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

    local procedure AssertEqualInteger(Expected: Integer; Actual: Integer; FailureMessage: Text)
    begin
        if Expected <> Actual then
            Error('%1 Expected %2 but received %3.', FailureMessage, Expected, Actual);
    end;

    local procedure AssertEqualText(Expected: Text; Actual: Text; FailureMessage: Text)
    begin
        if Expected <> Actual then
            Error('%1 Expected "%2" but received "%3".', FailureMessage, Expected, Actual);
    end;
}
