codeunit 70591 "GPI Delivery Transport Mgt."
{
    procedure OpenEmailEditor(EmailMessage: Codeunit "Email Message"; SenderEmailAccount: Record "Email Account" temporary; var EmailAction: Enum "Email Action"; var ErrorText: Text): Boolean
    var
        IsHandled: Boolean;
        OperationSucceeded: Boolean;
    begin
        Clear(ErrorText);
        OnBeforeOpenEmailEditor(
            SenderEmailAccount."Email Address",
            EmailMessage.GetId(),
            IsHandled,
            OperationSucceeded,
            EmailAction,
            ErrorText);

        if IsHandled then
            exit(OperationSucceeded);

        ClearLastError();
        if not TryOpenEmailEditor(EmailMessage, SenderEmailAccount, EmailAction) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := 'The Business Central email editor returned an unexpected error.';
            exit(false);
        end;

        exit(true);
    end;

    procedure SendEmail(EmailMessage: Codeunit "Email Message"; SenderEmailAccount: Record "Email Account" temporary; var SentSuccessfully: Boolean; var ErrorText: Text): Boolean
    var
        IsHandled: Boolean;
        OperationSucceeded: Boolean;
    begin
        Clear(ErrorText);
        Clear(SentSuccessfully);
        OnBeforeSendEmail(
            SenderEmailAccount."Email Address",
            EmailMessage.GetId(),
            IsHandled,
            OperationSucceeded,
            SentSuccessfully,
            ErrorText);

        if IsHandled then
            exit(OperationSucceeded);

        ClearLastError();
        if not TrySendEmail(EmailMessage, SenderEmailAccount, SentSuccessfully) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := 'Business Central returned an error while sending the email.';
            exit(false);
        end;

        exit(true);
    end;

    procedure RequestArchiveUpload(ArchivePath: Text; FileName: Text[250]; var ExternalDeliveryId: Text[2048]; var SharePointUrl: Text[2048]; var ErrorText: Text): Boolean
    var
        IsHandled: Boolean;
        OperationSucceeded: Boolean;
    begin
        Clear(ExternalDeliveryId);
        Clear(SharePointUrl);
        Clear(ErrorText);

        OnBeforeArchiveUpload(
            ArchivePath,
            FileName,
            IsHandled,
            OperationSucceeded,
            ExternalDeliveryId,
            SharePointUrl,
            ErrorText);

        if IsHandled then
            exit(OperationSucceeded);

        ErrorText := 'No archive transport handler was registered for this request.';
        exit(false);
    end;

    [TryFunction]
    local procedure TryOpenEmailEditor(EmailMessage: Codeunit "Email Message"; SenderEmailAccount: Record "Email Account" temporary; var EmailAction: Enum "Email Action")
    var
        Email: Codeunit Email;
    begin
        EmailAction := Email.OpenInEditorModally(EmailMessage, SenderEmailAccount);
    end;

    [TryFunction]
    local procedure TrySendEmail(EmailMessage: Codeunit "Email Message"; SenderEmailAccount: Record "Email Account" temporary; var SentSuccessfully: Boolean)
    var
        Email: Codeunit Email;
    begin
        SentSuccessfully := Email.Send(EmailMessage, SenderEmailAccount);
    end;

    [IntegrationEvent(false, false)]
    local procedure OnBeforeOpenEmailEditor(SenderEmailAddress: Text; EmailMessageId: Guid; var IsHandled: Boolean; var OperationSucceeded: Boolean; var EmailAction: Enum "Email Action"; var ErrorText: Text)
    begin
    end;

    [IntegrationEvent(false, false)]
    local procedure OnBeforeSendEmail(SenderEmailAddress: Text; EmailMessageId: Guid; var IsHandled: Boolean; var OperationSucceeded: Boolean; var SentSuccessfully: Boolean; var ErrorText: Text)
    begin
    end;

    [IntegrationEvent(false, false)]
    local procedure OnBeforeArchiveUpload(ArchivePath: Text; FileName: Text[250]; var IsHandled: Boolean; var OperationSucceeded: Boolean; var ExternalDeliveryId: Text[2048]; var SharePointUrl: Text[2048]; var ErrorText: Text)
    begin
    end;
}
