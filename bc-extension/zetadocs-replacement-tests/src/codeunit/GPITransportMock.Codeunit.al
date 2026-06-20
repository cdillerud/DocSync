codeunit 70708 "GPI Transport Mock"
{
    EventSubscriberInstance = Manual;

    procedure ConfigureEmailSend(OperationSucceeded: Boolean; SentSuccessfully: Boolean; ErrorText: Text)
    begin
        HandleEmailSend := true;
        EmailSendOperationSucceeded := OperationSucceeded;
        EmailWasSent := SentSuccessfully;
        EmailSendErrorText := ErrorText;
    end;

    procedure ConfigureEmailEditor(OperationSucceeded: Boolean; EmailAction: Enum "Email Action"; ErrorText: Text)
    begin
        HandleEmailEditor := true;
        EmailEditorOperationSucceeded := OperationSucceeded;
        ConfiguredEmailAction := EmailAction;
        EmailEditorErrorText := ErrorText;
    end;

    procedure ConfigureArchive(OperationSucceeded: Boolean; ExternalDeliveryId: Text; SharePointUrl: Text; ErrorText: Text)
    begin
        HandleArchive := true;
        ArchiveOperationSucceeded := OperationSucceeded;
        ConfiguredExternalDeliveryId := ExternalDeliveryId;
        ConfiguredSharePointUrl := SharePointUrl;
        ArchiveErrorText := ErrorText;
    end;

    procedure GetCapturedSenderEmail(): Text
    begin
        exit(CapturedSenderEmail);
    end;

    procedure GetCapturedEmailMessageId(): Guid
    begin
        exit(CapturedEmailMessageId);
    end;

    procedure GetCapturedArchivePath(): Text
    begin
        exit(CapturedArchivePath);
    end;

    procedure GetCapturedArchiveFileName(): Text
    begin
        exit(CapturedArchiveFileName);
    end;

    [EventSubscriber(ObjectType::Codeunit, Codeunit::"GPI Delivery Transport Mgt.", 'OnBeforeSendEmail', '', false, false)]
    local procedure HandleSendEmail(SenderEmailAddress: Text; EmailMessageId: Guid; var IsHandled: Boolean; var OperationSucceeded: Boolean; var SentSuccessfully: Boolean; var ErrorText: Text)
    begin
        if not HandleEmailSend then
            exit;

        CapturedSenderEmail := SenderEmailAddress;
        CapturedEmailMessageId := EmailMessageId;
        IsHandled := true;
        OperationSucceeded := EmailSendOperationSucceeded;
        SentSuccessfully := EmailWasSent;
        ErrorText := EmailSendErrorText;
    end;

    [EventSubscriber(ObjectType::Codeunit, Codeunit::"GPI Delivery Transport Mgt.", 'OnBeforeOpenEmailEditor', '', false, false)]
    local procedure HandleOpenEmailEditor(SenderEmailAddress: Text; EmailMessageId: Guid; var IsHandled: Boolean; var OperationSucceeded: Boolean; var EmailAction: Enum "Email Action"; var ErrorText: Text)
    begin
        if not HandleEmailEditor then
            exit;

        CapturedSenderEmail := SenderEmailAddress;
        CapturedEmailMessageId := EmailMessageId;
        IsHandled := true;
        OperationSucceeded := EmailEditorOperationSucceeded;
        EmailAction := ConfiguredEmailAction;
        ErrorText := EmailEditorErrorText;
    end;

    [EventSubscriber(ObjectType::Codeunit, Codeunit::"GPI Delivery Transport Mgt.", 'OnBeforeArchiveUpload', '', false, false)]
    local procedure HandleArchiveUpload(ArchivePath: Text; FileName: Text[250]; var IsHandled: Boolean; var OperationSucceeded: Boolean; var ExternalDeliveryId: Text[2048]; var SharePointUrl: Text[2048]; var ErrorText: Text)
    begin
        if not HandleArchive then
            exit;

        CapturedArchivePath := ArchivePath;
        CapturedArchiveFileName := FileName;
        IsHandled := true;
        OperationSucceeded := ArchiveOperationSucceeded;
        ExternalDeliveryId := ConfiguredExternalDeliveryId;
        SharePointUrl := ConfiguredSharePointUrl;
        ErrorText := ArchiveErrorText;
    end;

    var
        HandleEmailSend: Boolean;
        HandleEmailEditor: Boolean;
        HandleArchive: Boolean;
        EmailSendOperationSucceeded: Boolean;
        EmailWasSent: Boolean;
        EmailEditorOperationSucceeded: Boolean;
        ArchiveOperationSucceeded: Boolean;
        ConfiguredEmailAction: Enum "Email Action";
        EmailSendErrorText: Text;
        EmailEditorErrorText: Text;
        ArchiveErrorText: Text;
        ConfiguredExternalDeliveryId: Text;
        ConfiguredSharePointUrl: Text;
        CapturedSenderEmail: Text;
        CapturedEmailMessageId: Guid;
        CapturedArchivePath: Text;
        CapturedArchiveFileName: Text;
}
