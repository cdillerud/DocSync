codeunit 70522 "GPI Draft Email Mgt."
{
    Permissions =
        tabledata "Email Outbox" = r,
        tabledata "GPI Document Delivery Log" = rm;

    procedure OpenDraft(var DeliveryLog: Record "GPI Document Delivery Log")
    var
        EmailOutbox: Record "Email Outbox";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        EmailAction: Enum "Email Action";
        EmailMessageId: Guid;
        EmailAccountId: Guid;
        EmailConnector: Enum "Email Connector";
    begin
        if DeliveryLog.Status <> DeliveryLog.Status::"Saved As Draft" then
            Error('Delivery log entry %1 is not a saved draft.', DeliveryLog."Entry No.");

        EmailMessageId := DeliveryLog."Email Message ID";
        if IsNullGuid(EmailMessageId) then
            Error('Delivery log entry %1 does not contain an Email Message ID.', DeliveryLog."Entry No.");

        if not FindEmailOutboxByMessageId(EmailOutbox, EmailMessageId) then
            Error(
                'The native Business Central draft for delivery log entry %1 could not be found. It may have already been sent or discarded from Email Outbox.',
                DeliveryLog."Entry No.");

        if Email.GetOutboxEmailRecordStatus(EmailMessageId) <> Enum::"Email Status"::Draft then
            Error(
                'The native Business Central email for delivery log entry %1 is no longer a draft.',
                DeliveryLog."Entry No.");

        if not EmailMessage.Get(EmailMessageId) then
            Error('The email message for delivery log entry %1 no longer exists.', DeliveryLog."Entry No.");

        EmailAccountId := EmailOutbox.GetAccountId();
        EmailConnector := EmailOutbox.GetConnector();
        EmailAction := Email.OpenInEditorModally(EmailMessage, EmailAccountId, EmailConnector);

        UpdateDeliveryLogAfterEditor(DeliveryLog, EmailMessage, EmailAction);
    end;

    local procedure FindEmailOutboxByMessageId(var EmailOutbox: Record "Email Outbox"; EmailMessageId: Guid): Boolean
    begin
        if not EmailOutbox.FindSet() then
            exit(false);

        repeat
            if EmailOutbox.GetMessageId() = EmailMessageId then
                exit(true);
        until EmailOutbox.Next() = 0;

        exit(false);
    end;

    local procedure UpdateDeliveryLogAfterEditor(var DeliveryLog: Record "GPI Document Delivery Log"; EmailMessage: Codeunit "Email Message"; EmailAction: Enum "Email Action")
    var
        FinalToRecipients: List of [Text];
        FinalCCRecipients: List of [Text];
        FinalBCCRecipients: List of [Text];
    begin
        EmailMessage.GetRecipients(Enum::"Email Recipient Type"::"To", FinalToRecipients);
        EmailMessage.GetRecipients(Enum::"Email Recipient Type"::"Cc", FinalCCRecipients);
        EmailMessage.GetRecipients(Enum::"Email Recipient Type"::"Bcc", FinalBCCRecipients);

        DeliveryLog."To Recipients" := CopyStr(JoinRecipients(FinalToRecipients), 1, MaxStrLen(DeliveryLog."To Recipients"));
        DeliveryLog."CC Recipients" := CopyStr(JoinRecipients(FinalCCRecipients), 1, MaxStrLen(DeliveryLog."CC Recipients"));
        DeliveryLog."BCC Recipients" := CopyStr(JoinRecipients(FinalBCCRecipients), 1, MaxStrLen(DeliveryLog."BCC Recipients"));
        DeliveryLog.Subject := CopyStr(EmailMessage.GetSubject(), 1, MaxStrLen(DeliveryLog.Subject));
        DeliveryLog."Completed Date/Time" := CurrentDateTime();
        DeliveryLog."Completed By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Completed By"));
        Clear(DeliveryLog."Error Message");

        case EmailAction of
            Enum::"Email Action"::Sent:
                begin
                    DeliveryLog.Status := DeliveryLog.Status::Sent;
                    DeliveryLog."External Delivery ID" := CopyStr(
                        EmailMessage.GetExternalId(),
                        1,
                        MaxStrLen(DeliveryLog."External Delivery ID"));
                end;
            Enum::"Email Action"::"Saved As Draft":
                DeliveryLog.Status := DeliveryLog.Status::"Saved As Draft";
            Enum::"Email Action"::Discarded:
                DeliveryLog.Status := DeliveryLog.Status::Discarded;
        end;

        DeliveryLog.Modify(true);
    end;

    local procedure JoinRecipients(Recipients: List of [Text]): Text
    var
        Recipient: Text;
        JoinedRecipients: Text;
    begin
        foreach Recipient in Recipients do begin
            if JoinedRecipients <> '' then
                JoinedRecipients += '; ';
            JoinedRecipients += Recipient;
        end;

        exit(JoinedRecipients);
    end;
}
