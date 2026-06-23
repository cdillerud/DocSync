codeunit 70512 "GPI Blanket Sales Order Email"
{
    procedure OpenDraft(var SalesHeader: Record "Sales Header")
    var
        DocumentPolicy: Codeunit "GPI Document Policy Mgt.";
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        EmailScenario: Codeunit "Email Scenario";
        DefaultEmailAccount: Record "Email Account";
        DeliveryLog: Record "GPI Document Delivery Log";
        SalesHeaderRef: RecordRef;
        AttachmentOutStream: OutStream;
        AttachmentInStream: InStream;
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedRoutingRuleEntries: Text[250];
        AttachmentName: Text[250];
        Subject: Text;
        Body: Text;
        EmailAction: Enum "Email Action";
        EmailErrorText: Text;
    begin
        SalesHeader.TestField("Document Type", SalesHeader."Document Type"::"Blanket Order");
        SalesHeader.TestField("No.");
        SalesHeader.TestField("Sell-to Customer No.");

        DocumentPolicy.ResolveBlanketSalesOrderRecipients(
            SalesHeader,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries);

        if ToRecipients.Count() = 0 then
            Error(
                'No email recipient was resolved for Blanket Sales Order %1. Add a matching customer routing rule or an email to the contact selected on the Blanket Sales Order.',
                SalesHeader."No.");

        Subject := StrSubstNo('Blanket Sales Order %1', SalesHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Please find attached Blanket Sales Order %1.</p><p>Thank you,</p>',
            SalesHeader."No.");
        AttachmentName := CopyStr(StrSubstNo('Blanket-Sales-Order %1.pdf', SalesHeader."No."), 1, MaxStrLen(AttachmentName));

        SalesHeader.SetRecFilter();
        SalesHeaderRef.GetTable(SalesHeader);
        TempBlob.CreateOutStream(AttachmentOutStream);
        Report.SaveAs(Report::"GPI Blanket Sales Order", '', ReportFormat::Pdf, AttachmentOutStream, SalesHeaderRef);

        EmailMessage.Create(ToRecipients, Subject, Body, true, CCRecipients, BCCRecipients);
        TempBlob.CreateInStream(AttachmentInStream);
        EmailMessage.AddAttachment(AttachmentName, 'application/pdf', AttachmentInStream);
        Email.AddRelation(
            EmailMessage,
            Database::"Sales Header",
            SalesHeader.SystemId,
            Enum::"Email Relation Type"::"Primary Source",
            Enum::"Email Relation Origin"::"Compose Context");

        Clear(DefaultEmailAccount);
        EmailScenario.GetDefaultEmailAccount(DefaultEmailAccount);
        CreateDeliveryLog(
            DeliveryLog,
            SalesHeader,
            AttachmentName,
            Subject,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            EmailMessage,
            DefaultEmailAccount,
            TempBlob);

        Commit();
        if not TryOpenEmailEditor(EmailMessage, EmailAction) then begin
            EmailErrorText := GetLastErrorText();
            if EmailErrorText = '' then
                EmailErrorText := 'The Business Central email editor returned an unexpected error.';

            UpdateDeliveryLogFailed(DeliveryLog, EmailErrorText);
            Commit();
            Error('%1', EmailErrorText);
        end;

        UpdateDeliveryLogAfterEditor(DeliveryLog, EmailMessage, EmailAction);
    end;

    procedure Preview(var SalesHeader: Record "Sales Header")
    begin
        SalesHeader.TestField("Document Type", SalesHeader."Document Type"::"Blanket Order");
        SalesHeader.SetRecFilter();
        Report.RunModal(Report::"GPI Blanket Sales Order", true, false, SalesHeader);
    end;

    [TryFunction]
    local procedure TryOpenEmailEditor(EmailMessage: Codeunit "Email Message"; var EmailAction: Enum "Email Action")
    var
        Email: Codeunit Email;
    begin
        EmailAction := Email.OpenInEditorModally(EmailMessage);
    end;

    local procedure CreateDeliveryLog(var DeliveryLog: Record "GPI Document Delivery Log"; SalesHeader: Record "Sales Header"; AttachmentName: Text[250]; Subject: Text; ToRecipients: List of [Text]; CCRecipients: List of [Text]; BCCRecipients: List of [Text]; AppliedRoutingRuleEntries: Text[250]; EmailMessage: Codeunit "Email Message"; DefaultEmailAccount: Record "Email Account"; TempBlob: Codeunit "Temp Blob")
    var
        DocumentInStream: InStream;
        DocumentOutStream: OutStream;
        SenderEmailAddress: Text;
    begin
        SenderEmailAddress := DefaultEmailAccount."Email Address";
        if SenderEmailAddress = '' then
            SenderEmailAddress := UserId();

        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryLog."Delivery Document Type"::"Blanket Sales Order";
        DeliveryLog.Status := DeliveryLog.Status::Created;
        DeliveryLog."Sales Order No." := SalesHeader."No.";
        DeliveryLog."Sales Order SystemId" := SalesHeader.SystemId;
        DeliveryLog."Customer No." := SalesHeader."Sell-to Customer No.";
        DeliveryLog."Location Code" := SalesHeader."Location Code";
        DeliveryLog."Report ID" := Report::"GPI Blanket Sales Order";
        DeliveryLog."Attachment Filename" := AttachmentName;
        DeliveryLog."To Recipients" := CopyStr(JoinRecipients(ToRecipients), 1, MaxStrLen(DeliveryLog."To Recipients"));
        DeliveryLog."CC Recipients" := CopyStr(JoinRecipients(CCRecipients), 1, MaxStrLen(DeliveryLog."CC Recipients"));
        DeliveryLog."BCC Recipients" := CopyStr(JoinRecipients(BCCRecipients), 1, MaxStrLen(DeliveryLog."BCC Recipients"));
        DeliveryLog.Subject := CopyStr(Subject, 1, MaxStrLen(DeliveryLog.Subject));
        DeliveryLog."Email Message ID" := EmailMessage.GetId();
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog."Created By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Created By"));
        DeliveryLog."Source Table ID" := Database::"Sales Header";
        DeliveryLog."Source SystemId" := SalesHeader.SystemId;
        DeliveryLog."Source Document Type" := CopyStr(Format(SalesHeader."Document Type"), 1, MaxStrLen(DeliveryLog."Source Document Type"));
        DeliveryLog."Source Document No." := SalesHeader."No.";
        DeliveryLog."Source Party Type" := 'Customer';
        DeliveryLog."Source Party No." := SalesHeader."Sell-to Customer No.";
        DeliveryLog."Sender User" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Sender User"));
        DeliveryLog."Sender Email Address" := CopyStr(SenderEmailAddress, 1, MaxStrLen(DeliveryLog."Sender Email Address"));
        DeliveryLog."Sender Policy" := 'Current User';
        DeliveryLog."Routing Rule Entry Nos." := AppliedRoutingRuleEntries;
        DeliveryLog."Sender Account Name" := CopyStr(DefaultEmailAccount.Name, 1, MaxStrLen(DeliveryLog."Sender Account Name"));
        DeliveryLog."Sender Connector" := CopyStr(Format(DefaultEmailAccount.Connector), 1, MaxStrLen(DeliveryLog."Sender Connector"));
        DeliveryLog."Sender Account ID" := DefaultEmailAccount."Account Id";
        DeliveryLog.Insert(true);

        TempBlob.CreateInStream(DocumentInStream);
        DeliveryLog."Document Content".CreateOutStream(DocumentOutStream);
        CopyStream(DocumentOutStream, DocumentInStream);
        DeliveryLog.Modify(true);
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
                    DeliveryLog."External Delivery ID" := CopyStr(EmailMessage.GetExternalId(), 1, MaxStrLen(DeliveryLog."External Delivery ID"));
                end;
            Enum::"Email Action"::"Saved As Draft":
                DeliveryLog.Status := DeliveryLog.Status::"Saved As Draft";
            Enum::"Email Action"::Discarded:
                DeliveryLog.Status := DeliveryLog.Status::Discarded;
        end;

        DeliveryLog.Modify(true);
    end;

    local procedure UpdateDeliveryLogFailed(var DeliveryLog: Record "GPI Document Delivery Log"; EmailErrorText: Text)
    begin
        DeliveryLog.Status := DeliveryLog.Status::Failed;
        DeliveryLog."Completed Date/Time" := CurrentDateTime();
        DeliveryLog."Completed By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Completed By"));
        DeliveryLog."Error Message" := CopyStr(EmailErrorText, 1, MaxStrLen(DeliveryLog."Error Message"));
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