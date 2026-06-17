codeunit 70510 "GPI Sales Order Email"
{
    procedure OpenSalesOrderConfirmationDraft(var SalesHeader: Record "Sales Header")
    var
        ToRecipients: List of [Text];
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        BuildCustomerRecipients(SalesHeader, ToRecipients);
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
            AttachmentName,
            ToRecipients);
    end;

    procedure OpenPrepaymentNoticeDraft(var SalesHeader: Record "Sales Header")
    var
        ToRecipients: List of [Text];
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        BuildCustomerRecipients(SalesHeader, ToRecipients);
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
            AttachmentName,
            ToRecipients);
    end;

    procedure OpenPickTicketDraft(var SalesHeader: Record "Sales Header")
    var
        ToRecipients: List of [Text];
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        BuildLocationRecipients(SalesHeader, ToRecipients);
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
            AttachmentName,
            ToRecipients);
    end;

    local procedure OpenSalesDocumentDraft(var SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; ReportId: Integer; Subject: Text; Body: Text; AttachmentName: Text[250]; var ToRecipients: List of [Text])
    var
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        EmailScenario: Codeunit "Email Scenario";
        DefaultEmailAccount: Record "Email Account";
        DeliveryLog: Record "GPI Document Delivery Log";
        SalesHeaderRef: RecordRef;
        AttachmentOutStream: OutStream;
        AttachmentInStream: InStream;
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        SalespersonEmail: Text;
        InsideSalespersonCode: Code[20];
        InsideSalespersonEmail: Text;
        CurrentUserEmail: Text;
        AppliedRoutingRuleEntries: Text[250];
        EmailAction: Enum "Email Action";
        EmailErrorText: Text;
    begin
        SalesHeader.TestField("Document Type", SalesHeader."Document Type"::Order);
        SalesHeader.TestField("No.");
        SalesHeader.TestField("Sell-to Customer No.");

        CurrentUserEmail := UserId();

        SalespersonEmail := GetSalespersonEmail(SalesHeader."Salesperson Code");
        AddCcRecipient(CCRecipients, SalespersonEmail, ToRecipients, CurrentUserEmail);

        InsideSalespersonCode := GetInsideSalespersonCode(SalesHeader);
        InsideSalespersonEmail := GetSalespersonEmail(InsideSalespersonCode);
        AddCcRecipient(CCRecipients, InsideSalespersonEmail, ToRecipients, CurrentUserEmail);

        ApplyRoutingRules(
            SalesHeader,
            DeliveryDocumentType,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries);
        NormalizeRecipientLists(ToRecipients, CCRecipients, BCCRecipients);

        if ToRecipients.Count() = 0 then
            Error('No email recipients were resolved for Sales Order %1 after document routing rules were applied.', SalesHeader."No.");

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

    local procedure ApplyRoutingRules(SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250])
    var
        RoutingRule: Record "GPI Document Routing Rule";
    begin
        RoutingRule.SetCurrentKey(Enabled, "Delivery Document Type", Priority, "Entry No.");
        RoutingRule.SetRange(Enabled, true);
        RoutingRule.SetRange("Delivery Document Type", DeliveryDocumentType);

        if not RoutingRule.FindSet() then
            exit;

        repeat
            if RoutingRuleMatchesSalesOrder(RoutingRule, SalesHeader) and
               RoutingRuleIsActive(RoutingRule, Today)
            then begin
                if RoutingRule."Recipient Action" = RoutingRule."Recipient Action"::Replace then begin
                    Clear(ToRecipients);
                    Clear(CCRecipients);
                    Clear(BCCRecipients);
                end;

                AddRecipientsFromText(ToRecipients, RoutingRule."To Addresses");
                AddRecipientsFromText(CCRecipients, RoutingRule."CC Addresses");
                AddRecipientsFromText(BCCRecipients, RoutingRule."BCC Addresses");
                AppendRoutingRuleEntry(AppliedRoutingRuleEntries, RoutingRule."Entry No.");
            end;
        until RoutingRule.Next() = 0;
    end;

    local procedure RoutingRuleMatchesSalesOrder(RoutingRule: Record "GPI Document Routing Rule"; SalesHeader: Record "Sales Header"): Boolean
    begin
        if RoutingRule."Vendor No." <> '' then
            exit(false);

        if (RoutingRule."Customer No." <> '') and
           (RoutingRule."Customer No." <> SalesHeader."Sell-to Customer No.")
        then
            exit(false);

        if (RoutingRule."Location Code" <> '') and
           (RoutingRule."Location Code" <> SalesHeader."Location Code")
        then
            exit(false);

        exit(true);
    end;

    local procedure RoutingRuleIsActive(RoutingRule: Record "GPI Document Routing Rule"; EvaluationDate: Date): Boolean
    begin
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

    local procedure AppendRoutingRuleEntry(var AppliedRoutingRuleEntries: Text[250]; EntryNo: Integer)
    var
        EntryText: Text;
    begin
        EntryText := Format(EntryNo);
        if AppliedRoutingRuleEntries = '' then
            AppliedRoutingRuleEntries := CopyStr(EntryText, 1, MaxStrLen(AppliedRoutingRuleEntries))
        else
            AppliedRoutingRuleEntries := CopyStr(
                StrSubstNo('%1, %2', AppliedRoutingRuleEntries, EntryText),
                1,
                MaxStrLen(AppliedRoutingRuleEntries));
    end;

    local procedure NormalizeRecipientLists(var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text])
    var
        NormalizedToRecipients: List of [Text];
        NormalizedCCRecipients: List of [Text];
        NormalizedBCCRecipients: List of [Text];
        Recipient: Text;
    begin
        foreach Recipient in ToRecipients do
            AddUniqueRecipient(NormalizedToRecipients, Recipient);

        foreach Recipient in CCRecipients do
            if not IsRecipientInList(NormalizedToRecipients, LowerCase(Recipient)) then
                AddUniqueRecipient(NormalizedCCRecipients, Recipient);

        foreach Recipient in BCCRecipients do
            if not IsRecipientInList(NormalizedToRecipients, LowerCase(Recipient)) and
               not IsRecipientInList(NormalizedCCRecipients, LowerCase(Recipient))
            then
                AddUniqueRecipient(NormalizedBCCRecipients, Recipient);

        ReplaceRecipientList(ToRecipients, NormalizedToRecipients);
        ReplaceRecipientList(CCRecipients, NormalizedCCRecipients);
        ReplaceRecipientList(BCCRecipients, NormalizedBCCRecipients);
    end;

    local procedure ReplaceRecipientList(var TargetRecipients: List of [Text]; SourceRecipients: List of [Text])
    var
        Recipient: Text;
    begin
        Clear(TargetRecipients);
        foreach Recipient in SourceRecipients do
            TargetRecipients.Add(Recipient);
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

    local procedure BuildCustomerRecipients(SalesHeader: Record "Sales Header"; var ToRecipients: List of [Text])
    var
        RecipientText: Text;
    begin
        RecipientText := GetCustomerRecipientText(SalesHeader);
        if RecipientText <> '' then
            AddRecipientsFromText(ToRecipients, RecipientText);
    end;

    local procedure BuildLocationRecipients(SalesHeader: Record "Sales Header"; var ToRecipients: List of [Text])
    var
        Location: Record Location;
    begin
        SalesHeader.TestField("Location Code");

        if not Location.Get(SalesHeader."Location Code") then
            Error('Location %1 could not be found for Sales Order %2.', SalesHeader."Location Code", SalesHeader."No.");

        if Location."E-Mail" <> '' then
            AddRecipientsFromText(ToRecipients, Location."E-Mail");
    end;

    local procedure GetCustomerRecipientText(SalesHeader: Record "Sales Header"): Text
    var
        Contact: Record Contact;
        Customer: Record Customer;
    begin
        if SalesHeader."Sell-to Contact No." <> '' then
            if Contact.Get(SalesHeader."Sell-to Contact No.") then
                if Contact."E-Mail" <> '' then
                    exit(Contact."E-Mail");

        if SalesHeader."Sell-to E-Mail" <> '' then
            exit(SalesHeader."Sell-to E-Mail");

        if Customer.Get(SalesHeader."Sell-to Customer No.") then
            exit(Customer."E-Mail");

        exit('');
    end;

    local procedure GetSalespersonEmail(SalespersonCode: Code[20]): Text
    var
        Salesperson: Record "Salesperson/Purchaser";
    begin
        if SalespersonCode = '' then
            exit('');

        if Salesperson.Get(SalespersonCode) then
            exit(Salesperson."E-Mail");

        exit('');
    end;

    local procedure GetInsideSalespersonCode(SalesHeader: Record "Sales Header"): Code[20]
    var
        SalesHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateName: Text;
        CandidateCaption: Text;
        CandidateValue: Text;
    begin
        SalesHeaderRef.GetTable(SalesHeader);

        for FieldIndex := 1 to SalesHeaderRef.FieldCount do begin
            CandidateField := SalesHeaderRef.FieldIndex(FieldIndex);
            CandidateName := LowerCase(CandidateField.Name);
            CandidateCaption := LowerCase(CandidateField.Caption);

            if IsInsideSalespersonField(CandidateName, CandidateCaption) and
               (StrPos(CandidateName, 'backup') = 0) and
               (StrPos(CandidateCaption, 'backup') = 0)
            then begin
                CandidateValue := Format(CandidateField.Value);
                exit(CopyStr(CandidateValue, 1, 20));
            end;
        end;

        exit('');
    end;

    local procedure IsInsideSalespersonField(FieldNameText: Text; FieldCaptionText: Text): Boolean
    begin
        exit(
            (StrPos(FieldNameText, 'inside salesperson') > 0) or
            (StrPos(FieldCaptionText, 'inside salesperson') > 0) or
            (StrPos(FieldNameText, 'inside sales') > 0) or
            (StrPos(FieldCaptionText, 'inside sales') > 0) or
            (FieldNameText = 'isr') or
            (FieldCaptionText = 'isr') or
            (StrPos(FieldNameText, 'isr code') > 0) or
            (StrPos(FieldCaptionText, 'isr code') > 0));
    end;

    local procedure AddRecipientsFromText(var Recipients: List of [Text]; RecipientText: Text)
    var
        RemainingText: Text;
        Recipient: Text;
        SeparatorPosition: Integer;
    begin
        RemainingText := ConvertStr(RecipientText, ',', ';');

        while RemainingText <> '' do begin
            SeparatorPosition := StrPos(RemainingText, ';');
            if SeparatorPosition = 0 then begin
                Recipient := RemainingText;
                RemainingText := '';
            end else begin
                Recipient := CopyStr(RemainingText, 1, SeparatorPosition - 1);
                RemainingText := CopyStr(RemainingText, SeparatorPosition + 1);
            end;

            Recipient := DelChr(Recipient, '<>', ' ');
            AddUniqueRecipient(Recipients, Recipient);
        end;
    end;

    local procedure AddUniqueRecipient(var Recipients: List of [Text]; EmailAddress: Text)
    var
        ExistingRecipient: Text;
        NormalizedEmail: Text;
    begin
        NormalizedEmail := LowerCase(EmailAddress);
        if NormalizedEmail = '' then
            exit;

        foreach ExistingRecipient in Recipients do
            if NormalizedEmail = LowerCase(ExistingRecipient) then
                exit;

        Recipients.Add(EmailAddress);
    end;

    local procedure AddCcRecipient(var CCRecipients: List of [Text]; EmailAddress: Text; ToRecipients: List of [Text]; SenderAddress: Text)
    var
        ExistingRecipient: Text;
        NormalizedEmail: Text;
    begin
        NormalizedEmail := LowerCase(EmailAddress);
        if NormalizedEmail = '' then
            exit;

        if IsRecipientInList(ToRecipients, NormalizedEmail) then
            exit;

        if NormalizedEmail = LowerCase(SenderAddress) then
            exit;

        foreach ExistingRecipient in CCRecipients do
            if NormalizedEmail = LowerCase(ExistingRecipient) then
                exit;

        CCRecipients.Add(EmailAddress);
    end;

    local procedure IsRecipientInList(Recipients: List of [Text]; NormalizedEmail: Text): Boolean
    var
        ExistingRecipient: Text;
    begin
        foreach ExistingRecipient in Recipients do
            if NormalizedEmail = LowerCase(ExistingRecipient) then
                exit(true);

        exit(false);
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
