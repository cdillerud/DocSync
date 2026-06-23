codeunit 70510 "GPI Sales Order Email"
{
    procedure OpenSalesOrderConfirmationDraft(var SalesHeader: Record "Sales Header")
    var
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        Subject := StrSubstNo('Sales Order Confirmation %1', SalesHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Please find attached Sales Order Confirmation %1.</p><p>Thank you,</p>',
            SalesHeader."No.");
        AttachmentName := CopyStr(StrSubstNo('Sales-Order %1.pdf', SalesHeader."No."), 1, MaxStrLen(AttachmentName));

        OpenSalesDocumentDraft(
            SalesHeader,
            Enum::"GPI Delivery Document Type"::"Order Confirmation",
            Report::"GPI Sales Order Confirmation",
            Subject,
            Body,
            AttachmentName);
    end;

    procedure OpenPrepaymentNoticeDraft(var SalesHeader: Record "Sales Header")
    var
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        Subject := StrSubstNo('Prepayment Notice - Order %1', SalesHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Please find attached the prepayment notice for Sales Order %1.</p><p>Thank you,</p>',
            SalesHeader."No.");
        AttachmentName := CopyStr(StrSubstNo('Pre-Payment - Order %1.pdf', SalesHeader."No."), 1, MaxStrLen(AttachmentName));

        OpenSalesDocumentDraft(
            SalesHeader,
            Enum::"GPI Delivery Document Type"::"Prepayment Notice",
            Report::"GPI Prepayment Notice",
            Subject,
            Body,
            AttachmentName);
    end;

    procedure OpenPickTicketDraft(var SalesHeader: Record "Sales Header")
    var
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        Subject := StrSubstNo('Pick Ticket - Order %1', SalesHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Please find attached the pick ticket for Sales Order %1.</p><p>Thank you,</p>',
            SalesHeader."No.");
        AttachmentName := CopyStr(StrSubstNo('Pick-Ticket - Order %1.pdf', SalesHeader."No."), 1, MaxStrLen(AttachmentName));

        OpenSalesDocumentDraft(
            SalesHeader,
            Enum::"GPI Delivery Document Type"::"Pick Ticket",
            Report::"GPI Pick Ticket",
            Subject,
            Body,
            AttachmentName);
    end;

    local procedure OpenSalesDocumentDraft(var SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; ReportId: Integer; Subject: Text; Body: Text; AttachmentName: Text[250])
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
        EmailAction: Enum "Email Action";
        EmailErrorText: Text;
    begin
        SalesHeader.TestField("Document Type", SalesHeader."Document Type"::Order);
        SalesHeader.TestField("No.");
        SalesHeader.TestField("Sell-to Customer No.");

        if DeliveryDocumentType = DeliveryDocumentType::"Prepayment Notice" then
            EnsurePendingPrepaymentStatus(SalesHeader)
        else
            DocumentPolicy.EnsureSalesSendAllowed(SalesHeader, DeliveryDocumentType);

        DocumentPolicy.ResolveSalesDocumentRecipients(
            SalesHeader,
            DeliveryDocumentType,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries);

        if ToRecipients.Count() = 0 then
            Error(
                'No email recipient was resolved for %1 %2. Add a matching customer routing rule or an email to the contact selected on the Sales Order. Pick Tickets use the Location Card email when no customer rule applies.',
                Format(DeliveryDocumentType),
                SalesHeader."No.");

        SalesHeader.SetRecFilter();
        SalesHeaderRef.GetTable(SalesHeader);
        TempBlob.CreateOutStream(AttachmentOutStream);
        Report.SaveAs(ReportId, '', ReportFormat::Pdf, AttachmentOutStream, SalesHeaderRef);

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
            DeliveryDocumentType,
            ReportId,
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
        if EmailAction = Enum::"Email Action"::Sent then
            MarkSalesDocumentSent(SalesHeader, DeliveryDocumentType);
    end;

    local procedure EnsurePendingPrepaymentStatus(SalesHeader: Record "Sales Header")
    var
        CurrentStatus: Text;
    begin
        CurrentStatus := Format(SalesHeader.Status);
        if LowerCase(CurrentStatus) <> 'pending prepayment' then
            Error(
                'Prepayment Notice for Sales Order %1 can be previewed, but it cannot be sent until Status is Pending Prepayment. Current Status: %2.',
                SalesHeader."No.",
                CurrentStatus);
    end;

    [TryFunction]
    local procedure TryOpenEmailEditor(EmailMessage: Codeunit "Email Message"; var EmailAction: Enum "Email Action")
    var
        Email: Codeunit Email;
    begin
        EmailAction := Email.OpenInEditorModally(EmailMessage);
    end;

    local procedure CreateDeliveryLog(var DeliveryLog: Record "GPI Document Delivery Log"; SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; ReportId: Integer; AttachmentName: Text[250]; Subject: Text; ToRecipients: List of [Text]; CCRecipients: List of [Text]; BCCRecipients: List of [Text]; AppliedRoutingRuleEntries: Text[250]; EmailMessage: Codeunit "Email Message"; DefaultEmailAccount: Record "Email Account"; TempBlob: Codeunit "Temp Blob")
    var
        DocumentInStream: InStream;
        DocumentOutStream: OutStream;
        SenderEmailAddress: Text;
    begin
        SenderEmailAddress := DefaultEmailAccount."Email Address";
        if SenderEmailAddress = '' then
            SenderEmailAddress := UserId();

        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryDocumentType;
        DeliveryLog.Status := DeliveryLog.Status::Created;
        DeliveryLog."Sales Order No." := SalesHeader."No.";
        DeliveryLog."Sales Order SystemId" := SalesHeader.SystemId;
        DeliveryLog."Customer No." := SalesHeader."Sell-to Customer No.";
        DeliveryLog."Location Code" := SalesHeader."Location Code";
        DeliveryLog."Report ID" := ReportId;
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

    local procedure MarkSalesDocumentSent(var SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type")
    begin
        case DeliveryDocumentType of
            DeliveryDocumentType::"Order Confirmation":
                SetBooleanFieldBySearch(SalesHeader, 'order confirmation sent', 'confirmation sent');
            DeliveryDocumentType::"Prepayment Notice":
                SetBooleanFieldBySearch(SalesHeader, 'prepayment sent', 'pre-payment sent');
            DeliveryDocumentType::"Pick Ticket":
                SetBooleanFieldBySearch(SalesHeader, 'picklist sent', 'pick list sent');
        end;
    end;

    local procedure SetBooleanFieldBySearch(SalesHeader: Record "Sales Header"; PrimarySearchText: Text; AlternateSearchText: Text)
    var
        SalesHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        FieldIdentity: Text;
    begin
        SalesHeaderRef.GetTable(SalesHeader);
        for FieldIndex := 1 to SalesHeaderRef.FieldCount do begin
            CandidateField := SalesHeaderRef.FieldIndex(FieldIndex);
            FieldIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if (StrPos(FieldIdentity, PrimarySearchText) > 0) or
               ((AlternateSearchText <> '') and (StrPos(FieldIdentity, AlternateSearchText) > 0))
            then begin
                CandidateField.Value := true;
                SalesHeaderRef.Modify(true);
                exit;
            end;
        end;
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