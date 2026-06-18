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
    begin
        if DeliveryLog.Status <> DeliveryLog.Status::"Saved As Draft" then
            Error('Delivery log entry %1 is not a saved draft.', DeliveryLog."Entry No.");

        if IsNullGuid(DeliveryLog."Email Message ID") then
            Error('Delivery log entry %1 does not contain an Email Message ID.', DeliveryLog."Entry No.");

        EmailOutbox.SetRange("Message Id", DeliveryLog."Email Message ID");
        EmailOutbox.SetRange(Status, EmailOutbox.Status::Draft);
        if not EmailOutbox.FindFirst() then
            Error(
                'The native Business Central draft for delivery log entry %1 could not be found. It may have already been sent or discarded from Email Outbox.',
                DeliveryLog."Entry No.");

        if not EmailMessage.Get(DeliveryLog."Email Message ID") then
            Error('The email message for delivery log entry %1 no longer exists.', DeliveryLog."Entry No.");

        EmailAction := Email.OpenInEditorModally(
            EmailMessage,
            EmailOutbox."Account Id",
            EmailOutbox.Connector);

        UpdateDeliveryLogAfterEditor(DeliveryLog, EmailMessage, EmailAction);
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
