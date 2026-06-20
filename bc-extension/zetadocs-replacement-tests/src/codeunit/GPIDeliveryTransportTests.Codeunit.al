codeunit 70709 "GPI Delivery Transport Tests"
{
    Subtype = Test;

    [Test]
    procedure MockedEmailSendReturnsSuccessWithoutSending()
    var
        Transport: Codeunit "GPI Delivery Transport Mgt.";
        TransportMock: Codeunit "GPI Transport Mock";
        EmailMessage: Codeunit "Email Message";
        SenderEmailAccount: Record "Email Account" temporary;
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        ErrorText: Text;
        SentSuccessfully: Boolean;
    begin
        CreateEmailMessage(EmailMessage, ToRecipients, CCRecipients, BCCRecipients);
        SenderEmailAccount."Email Address" := 'sender@example.com';
        TransportMock.ConfigureEmailSend(true, true, '');
        BindSubscription(TransportMock);

        AssertTrue(
            Transport.SendEmail(
                EmailMessage,
                SenderEmailAccount,
                SentSuccessfully,
                ErrorText),
            'The mocked email transport should report a successful operation.');

        UnbindSubscription(TransportMock);
        AssertTrue(SentSuccessfully, 'The mocked email transport did not report the message as sent.');
        AssertEqualText('', ErrorText, 'A successful mocked send returned an error.');
        AssertEqualText('sender@example.com', TransportMock.GetCapturedSenderEmail(), 'The sender account was not passed to the transport event.');
        AssertEqualGuid(EmailMessage.GetId(), TransportMock.GetCapturedEmailMessageId(), 'The email message ID was not passed to the transport event.');
    end;

    [Test]
    procedure MockedEmailSendReturnsControlledFailure()
    var
        Transport: Codeunit "GPI Delivery Transport Mgt.";
        TransportMock: Codeunit "GPI Transport Mock";
        EmailMessage: Codeunit "Email Message";
        SenderEmailAccount: Record "Email Account" temporary;
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        ErrorText: Text;
        SentSuccessfully: Boolean;
    begin
        CreateEmailMessage(EmailMessage, ToRecipients, CCRecipients, BCCRecipients);
        SenderEmailAccount."Email Address" := 'sender@example.com';
        TransportMock.ConfigureEmailSend(false, false, 'Mock send failure');
        BindSubscription(TransportMock);

        AssertFalse(
            Transport.SendEmail(
                EmailMessage,
                SenderEmailAccount,
                SentSuccessfully,
                ErrorText),
            'The mocked email transport should report the configured operation failure.');

        UnbindSubscription(TransportMock);
        AssertFalse(SentSuccessfully, 'A failed mocked send should not report the message as sent.');
        AssertEqualText('Mock send failure', ErrorText, 'The mocked send error was not returned.');
    end;

    [Test]
    procedure MockedEmailEditorReturnsConfiguredAction()
    var
        Transport: Codeunit "GPI Delivery Transport Mgt.";
        TransportMock: Codeunit "GPI Transport Mock";
        EmailMessage: Codeunit "Email Message";
        SenderEmailAccount: Record "Email Account" temporary;
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        EmailAction: Enum "Email Action";
        ErrorText: Text;
    begin
        CreateEmailMessage(EmailMessage, ToRecipients, CCRecipients, BCCRecipients);
        SenderEmailAccount."Email Address" := 'editor@example.com';
        TransportMock.ConfigureEmailEditor(true, EmailAction::Sent, '');
        BindSubscription(TransportMock);

        AssertTrue(
            Transport.OpenEmailEditor(
                EmailMessage,
                SenderEmailAccount,
                EmailAction,
                ErrorText),
            'The mocked email editor should report a successful operation.');

        UnbindSubscription(TransportMock);
        AssertEqualText(Format(EmailAction::Sent), Format(EmailAction), 'The mocked email editor returned the wrong action.');
        AssertEqualText('editor@example.com', TransportMock.GetCapturedSenderEmail(), 'The editor sender account was not captured.');
    end;

    [Test]
    procedure MockedArchiveReturnsExternalIdentifiers()
    var
        Transport: Codeunit "GPI Delivery Transport Mgt.";
        TransportMock: Codeunit "GPI Transport Mock";
        ExternalDeliveryId: Text[2048];
        SharePointUrl: Text[2048];
        ErrorText: Text;
    begin
        TransportMock.ConfigureArchive(
            true,
            'mock-item-123',
            'https://example.sharepoint.com/mock-item-123?web=1',
            '');
        BindSubscription(TransportMock);

        AssertTrue(
            Transport.RequestArchiveUpload(
                '06-19-2026/Customer/Sales',
                'Open-Order-Status.pdf',
                ExternalDeliveryId,
                SharePointUrl,
                ErrorText),
            'The mocked archive transport should report success.');

        UnbindSubscription(TransportMock);
        AssertEqualText('mock-item-123', ExternalDeliveryId, 'The mocked archive item ID was not returned.');
        AssertEqualText('https://example.sharepoint.com/mock-item-123?web=1', SharePointUrl, 'The mocked SharePoint URL was not returned.');
        AssertEqualText('06-19-2026/Customer/Sales', TransportMock.GetCapturedArchivePath(), 'The archive path was not passed to the transport event.');
        AssertEqualText('Open-Order-Status.pdf', TransportMock.GetCapturedArchiveFileName(), 'The archive filename was not passed to the transport event.');
    end;

    [Test]
    procedure ArchiveWithoutHandlerFailsSafely()
    var
        Transport: Codeunit "GPI Delivery Transport Mgt.";
        ExternalDeliveryId: Text[2048];
        SharePointUrl: Text[2048];
        ErrorText: Text;
    begin
        AssertFalse(
            Transport.RequestArchiveUpload(
                '06-19-2026/Customer/Sales',
                'Open-Order-Status.pdf',
                ExternalDeliveryId,
                SharePointUrl,
                ErrorText),
            'An archive request without a registered handler must not report success.');

        AssertEqualText('No archive transport handler was registered for this request.', ErrorText, 'The safe archive failure message changed.');
    end;

    local procedure CreateEmailMessage(var EmailMessage: Codeunit "Email Message"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text])
    begin
        ToRecipients.Add('recipient@example.com');
        EmailMessage.Create(
            ToRecipients,
            'Mock transport test',
            '<p>Mock transport test</p>',
            true,
            CCRecipients,
            BCCRecipients);
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

    local procedure AssertEqualGuid(Expected: Guid; Actual: Guid; FailureMessage: Text)
    begin
        if Expected <> Actual then
            Error('%1 Expected %2 but received %3.', FailureMessage, Expected, Actual);
    end;
}
