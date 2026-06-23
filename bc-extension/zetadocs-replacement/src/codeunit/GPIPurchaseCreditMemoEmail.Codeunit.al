codeunit 70525 "GPI Purchase Credit Memo Email"
{
    Permissions =
        tabledata "Purch. Cr. Memo Hdr." = rm,
        tabledata "GPI Document Delivery Log" = rimd,
        tabledata "GPI Document Routing Rule" = r;

    procedure PreviewPurchaseCreditMemo(PurchaseCreditMemoHeader: Record "Purch. Cr. Memo Hdr.")
    var
        TempBlob: Codeunit "Temp Blob";
        FileName: Text;
    begin
        ValidatePurchaseCreditMemo(PurchaseCreditMemoHeader);
        GeneratePurchaseCreditMemoPdf(PurchaseCreditMemoHeader, TempBlob);
        FileName := StrSubstNo('Purchase-Credit-Memo %1.pdf', PurchaseCreditMemoHeader."No.");

        if not File.ViewFromStream(TempBlob.CreateInStream(), FileName, true) then
            File.DownloadFromStream(
                TempBlob.CreateInStream(),
                'Download Purchase Credit Memo',
                '',
                'PDF files (*.pdf)|*.pdf',
                FileName);
    end;

    procedure OpenPurchaseCreditMemoDraft(var PurchaseCreditMemoHeader: Record "Purch. Cr. Memo Hdr.")
    var
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        EmailScenario: Codeunit "Email Scenario";
        EmailAccount: Record "Email Account";
        Vendor: Record Vendor;
        DeliveryLog: Record "GPI Document Delivery Log";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AttachmentInStream: InStream;
        AttachmentName: Text[250];
        Subject: Text;
        Body: Text;
        AppliedRuleEntries: Text[250];
        EmailAction: Enum "Email Action";
        ErrorText: Text;
    begin
        ValidatePurchaseCreditMemo(PurchaseCreditMemoHeader);
        ResolvePurchaseCreditMemoRecipients(
            PurchaseCreditMemoHeader,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries);

        if ToRecipients.Count() = 0 then begin
            UpdatePurchaseCreditMemoMissingRecipient(PurchaseCreditMemoHeader);
            Commit();
            Error(
                'No purchase credit memo recipient was found for vendor %1. Add an email to the document contact, populate the Vendor Card E-Mail field, or create a vendor-specific Purchase Credit Memo routing rule.',
                PurchaseCreditMemoHeader."Buy-from Vendor No.");
        end;

        if not EmailScenario.IsThereEmailAccountSetForScenario(Enum::"Email Scenario"::"GPI Purchase Credit Memo") then
            Error(
                'The GPI Purchase Credit Memo email scenario is not assigned to an email account. Open Email Scenario Setup and assign it to the Accounts Payable mailbox before emailing purchase credit memos.');

        EmailScenario.GetEmailAccount(Enum::"Email Scenario"::"GPI Purchase Credit Memo", EmailAccount);
        GeneratePurchaseCreditMemoPdf(PurchaseCreditMemoHeader, TempBlob);

        AttachmentName := CopyStr(
            StrSubstNo('Purchase-Credit-Memo %1.pdf', PurchaseCreditMemoHeader."No."),
            1,
            MaxStrLen(AttachmentName));
        Subject := StrSubstNo('Purchase Credit Memo %1', PurchaseCreditMemoHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Please find attached Purchase Credit Memo %1.</p><p>Thank you,</p>',
            PurchaseCreditMemoHeader."No.");

        EmailMessage.Create(ToRecipients, Subject, Body, true, CCRecipients, BCCRecipients);
        TempBlob.CreateInStream(AttachmentInStream);
        EmailMessage.AddAttachment(AttachmentName, 'application/pdf', AttachmentInStream);
        Email.AddRelation(
            EmailMessage,
            Database::"Purch. Cr. Memo Hdr.",
            PurchaseCreditMemoHeader.SystemId,
            Enum::"Email Relation Type"::"Primary Source",
            Enum::"Email Relation Origin"::"Compose Context");

        if Vendor.Get(PurchaseCreditMemoHeader."Buy-from Vendor No.") then
            Email.AddRelation(
                EmailMessage,
                Database::Vendor,
                Vendor.SystemId,
                Enum::"Email Relation Type"::"Related Entity",
                Enum::"Email Relation Origin"::"Compose Context");

        CreateDeliveryLog(
            DeliveryLog,
            PurchaseCreditMemoHeader,
            AttachmentName,
            Subject,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries,
            EmailAccount,
            EmailMessage,
            TempBlob);
        Commit();

        if not TryOpenEmailEditor(EmailMessage, EmailAccount, EmailAction) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := 'The Business Central email editor returned an unexpected error.';

            UpdateDeliveryLogFailed(DeliveryLog, ErrorText);
            Commit();
            Error('%1', ErrorText);
        end;

        UpdateDeliveryLogAfterEditor(DeliveryLog, EmailMessage, EmailAction);
    end;

    local procedure ValidatePurchaseCreditMemo(PurchaseCreditMemoHeader: Record "Purch. Cr. Memo Hdr.")
    begin
        PurchaseCreditMemoHeader.TestField("No.");
        PurchaseCreditMemoHeader.TestField("Buy-from Vendor No.");
    end;

    local procedure GeneratePurchaseCreditMemoPdf(PurchaseCreditMemoHeader: Record "Purch. Cr. Memo Hdr."; var TempBlob: Codeunit "Temp Blob")
    var
        HeaderRef: RecordRef;
        AttachmentOutStream: OutStream;
    begin
        PurchaseCreditMemoHeader.SetRecFilter();
        HeaderRef.GetTable(PurchaseCreditMemoHeader);
        TempBlob.CreateOutStream(AttachmentOutStream);
        Report.SaveAs(
            Report::"GPI Purchase Credit Memo",
            '',
            ReportFormat::Pdf,
            AttachmentOutStream,
            HeaderRef);

        if not TempBlob.HasValue() then
            Error('No PDF was generated for posted purchase credit memo %1.', PurchaseCreditMemoHeader."No.");
    end;

    [TryFunction]
    local procedure TryOpenEmailEditor(EmailMessage: Codeunit "Email Message"; EmailAccount: Record "Email Account"; var EmailAction: Enum "Email Action")
    var
        Email: Codeunit Email;
    begin
        EmailAction := Email.OpenInEditorModally(EmailMessage, EmailAccount);
    end;

    local procedure ResolvePurchaseCreditMemoRecipients(PurchaseCreditMemoHeader: Record "Purch. Cr. Memo Hdr."; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250])
    var
        SpecificRuleApplied: Boolean;
    begin
        SpecificRuleApplied := ApplyPurchaseCreditMemoRoutingRules(
            PurchaseCreditMemoHeader,
            true,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries);

        if ToRecipients.Count() = 0 then
            AddRecipientsFromText(
                ToRecipients,
                GetDocumentContactEmail(PurchaseCreditMemoHeader."Buy-from Contact No."));

        if ToRecipients.Count() = 0 then
            AddRecipientsFromText(
                ToRecipients,
                GetVendorCardEmail(PurchaseCreditMemoHeader."Buy-from Vendor No."));

        if not SpecificRuleApplied then
            ApplyPurchaseCreditMemoRoutingRules(
                PurchaseCreditMemoHeader,
                false,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRuleEntries);

        NormalizeRecipientLists(ToRecipients, CCRecipients, BCCRecipients);
    end;

    local procedure ApplyPurchaseCreditMemoRoutingRules(PurchaseCreditMemoHeader: Record "Purch. Cr. Memo Hdr."; SpecificVendorOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250]): Boolean
    var
        RoutingRule: Record "GPI Document Routing Rule";
        RuleApplied: Boolean;
    begin
        RoutingRule.SetCurrentKey(Enabled, "Delivery Document Type", Priority, "Entry No.");
        RoutingRule.SetRange(Enabled, true);
        RoutingRule.SetRange(
            "Delivery Document Type",
            Enum::"GPI Delivery Document Type"::"Purchase Credit Memo");

        if not RoutingRule.FindSet() then
            exit(false);

        repeat
            if PurchaseCreditMemoRoutingRuleMatches(RoutingRule, PurchaseCreditMemoHeader, SpecificVendorOnly) and
               RoutingRuleIsActive(RoutingRule, Today)
            then begin
                ApplyRoutingRule(RoutingRule, ToRecipients, CCRecipients, BCCRecipients);
                AppendRoutingRuleEntry(AppliedRuleEntries, RoutingRule."Entry No.");
                RuleApplied := true;
            end;
        until RoutingRule.Next() = 0;

        exit(RuleApplied);
    end;

    local procedure PurchaseCreditMemoRoutingRuleMatches(RoutingRule: Record "GPI Document Routing Rule"; PurchaseCreditMemoHeader: Record "Purch. Cr. Memo Hdr."; SpecificVendorOnly: Boolean): Boolean
    begin
        if RoutingRule."Customer No." <> '' then
            exit(false);

        if SpecificVendorOnly then begin
            if RoutingRule."Vendor No." <> PurchaseCreditMemoHeader."Buy-from Vendor No." then
                exit(false);
        end else
            if RoutingRule."Vendor No." <> '' then
                exit(false);

        if (RoutingRule."Location Code" <> '') and
           (RoutingRule."Location Code" <> PurchaseCreditMemoHeader."Location Code")
        then
            exit(false);

        exit(true);
    end;

    local procedure ApplyRoutingRule(RoutingRule: Record "GPI Document Routing Rule"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text])
    begin
        if RoutingRule."Recipient Action" = RoutingRule."Recipient Action"::Replace then begin
            Clear(ToRecipients);
            Clear(CCRecipients);
            Clear(BCCRecipients);
        end;

        AddRecipientsFromText(ToRecipients, RoutingRule."To Addresses");
        AddRecipientsFromText(CCRecipients, RoutingRule."CC Addresses");
        AddRecipientsFromText(BCCRecipients, RoutingRule."BCC Addresses");
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

    local procedure GetDocumentContactEmail(ContactNo: Code[20]): Text
    var
        Contact: Record Contact;
    begin
        if (ContactNo <> '') and Contact.Get(ContactNo) then
            exit(Contact."E-Mail");

        exit('');
    end;

    local procedure GetVendorCardEmail(VendorNo: Code[20]): Text
    var
        Vendor: Record Vendor;
    begin
        if Vendor.Get(VendorNo) then
            exit(Vendor."E-Mail");

        exit('');
    end;

    local procedure CreateDeliveryLog(var DeliveryLog: Record "GPI Document Delivery Log"; PurchaseCreditMemoHeader: Record "Purch. Cr. Memo Hdr."; AttachmentName: Text[250]; Subject: Text; ToRecipients: List of [Text]; CCRecipients: List of [Text]; BCCRecipients: List of [Text]; AppliedRuleEntries: Text[250]; EmailAccount: Record "Email Account"; EmailMessage: Codeunit "Email Message"; TempBlob: Codeunit "Temp Blob")
    var
        DocumentInStream: InStream;
        DocumentOutStream: OutStream;
    begin
        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryLog."Delivery Document Type"::"Purchase Credit Memo";
        DeliveryLog.Status := DeliveryLog.Status::Created;
        DeliveryLog."Location Code" := PurchaseCreditMemoHeader."Location Code";
        DeliveryLog."Report ID" := Report::"GPI Purchase Credit Memo";
        DeliveryLog."Attachment Filename" := AttachmentName;
        DeliveryLog."To Recipients" := CopyStr(JoinRecipients(ToRecipients), 1, MaxStrLen(DeliveryLog."To Recipients"));
        DeliveryLog."CC Recipients" := CopyStr(JoinRecipients(CCRecipients), 1, MaxStrLen(DeliveryLog."CC Recipients"));
        DeliveryLog."BCC Recipients" := CopyStr(JoinRecipients(BCCRecipients), 1, MaxStrLen(DeliveryLog."BCC Recipients"));
        DeliveryLog.Subject := CopyStr(Subject, 1, MaxStrLen(DeliveryLog.Subject));
        DeliveryLog."Email Message ID" := EmailMessage.GetId();
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog."Created By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Created By"));
        DeliveryLog."Source Table ID" := Database::"Purch. Cr. Memo Hdr.";
        DeliveryLog."Source SystemId" := PurchaseCreditMemoHeader.SystemId;
        DeliveryLog."Source Document Type" := 'Posted Purchase Credit Memo';
        DeliveryLog."Source Document No." := PurchaseCreditMemoHeader."No.";
        DeliveryLog."Source Party Type" := 'Vendor';
        DeliveryLog."Source Party No." := PurchaseCreditMemoHeader."Buy-from Vendor No.";
        DeliveryLog."Sender User" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Sender User"));
        DeliveryLog."Sender Email Address" := CopyStr(EmailAccount."Email Address", 1, MaxStrLen(DeliveryLog."Sender Email Address"));
        DeliveryLog."Sender Policy" := 'Email Scenario';
        DeliveryLog."Routing Rule Entry Nos." := AppliedRuleEntries;
        DeliveryLog."Sender Account Name" := CopyStr(EmailAccount.Name, 1, MaxStrLen(DeliveryLog."Sender Account Name"));
        DeliveryLog."Sender Connector" := CopyStr(Format(EmailAccount.Connector), 1, MaxStrLen(DeliveryLog."Sender Connector"));
        DeliveryLog."Sender Account ID" := EmailAccount."Account Id";
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

    local procedure UpdateDeliveryLogFailed(var DeliveryLog: Record "GPI Document Delivery Log"; ErrorText: Text)
    begin
        DeliveryLog.Status := DeliveryLog.Status::Failed;
        DeliveryLog."Completed Date/Time" := CurrentDateTime();
        DeliveryLog."Completed By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Completed By"));
        DeliveryLog."Error Message" := CopyStr(ErrorText, 1, MaxStrLen(DeliveryLog."Error Message"));
        DeliveryLog.Modify(true);
    end;

    local procedure UpdatePurchaseCreditMemoMissingRecipient(var PurchaseCreditMemoHeader: Record "Purch. Cr. Memo Hdr.")
    begin
        PurchaseCreditMemoHeader."GPI Purch Cr Memo Status" := PurchaseCreditMemoHeader."GPI Purch Cr Memo Status"::"Missing Recipient";
        Clear(PurchaseCreditMemoHeader."GPI Purch Cr Memo Recipient");
        PurchaseCreditMemoHeader."GPI Last Delivery Error" := CopyStr(
            StrSubstNo(
                'No purchase credit memo recipient was found for vendor %1. Add an email to the document contact, populate the Vendor Card E-Mail field, or create a vendor-specific Purchase Credit Memo routing rule.',
                PurchaseCreditMemoHeader."Buy-from Vendor No."),
            1,
            MaxStrLen(PurchaseCreditMemoHeader."GPI Last Delivery Error"));
        PurchaseCreditMemoHeader.Modify(false);
    end;

    [EventSubscriber(ObjectType::Table, Database::"GPI Document Delivery Log", 'OnAfterModifyEvent', '', false, false)]
    local procedure DeliveryLogOnAfterModify(var Rec: Record "GPI Document Delivery Log"; var xRec: Record "GPI Document Delivery Log"; RunTrigger: Boolean)
    begin
        if Rec."Source Table ID" <> Database::"Purch. Cr. Memo Hdr." then
            exit;

        UpdatePurchaseCreditMemoHeaderFromLog(Rec);
    end;

    local procedure UpdatePurchaseCreditMemoHeaderFromLog(DeliveryLog: Record "GPI Document Delivery Log")
    var
        PurchaseCreditMemoHeader: Record "Purch. Cr. Memo Hdr.";
    begin
        if not PurchaseCreditMemoHeader.Get(DeliveryLog."Source Document No.") then
            exit;

        PurchaseCreditMemoHeader."GPI Purch Cr Memo Status" := DeliveryLog.Status;
        PurchaseCreditMemoHeader."GPI Purch Cr Memo Recipient" := CopyStr(
            DeliveryLog."To Recipients",
            1,
            MaxStrLen(PurchaseCreditMemoHeader."GPI Purch Cr Memo Recipient"));
        PurchaseCreditMemoHeader."GPI Last Delivery Entry No." := DeliveryLog."Entry No.";
        PurchaseCreditMemoHeader."GPI Last Delivery Date/Time" := DeliveryLog."Completed Date/Time";
        PurchaseCreditMemoHeader."GPI Last Delivery Error" := CopyStr(
            DeliveryLog."Error Message",
            1,
            MaxStrLen(PurchaseCreditMemoHeader."GPI Last Delivery Error"));
        PurchaseCreditMemoHeader."GPI Last Sender Email" := CopyStr(
            DeliveryLog."Sender Email Address",
            1,
            MaxStrLen(PurchaseCreditMemoHeader."GPI Last Sender Email"));
        PurchaseCreditMemoHeader.Modify(false);
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
        NormalizedEmail := LowerCase(DelChr(EmailAddress, '<>', ' '));
        if NormalizedEmail = '' then
            exit;

        foreach ExistingRecipient in Recipients do
            if NormalizedEmail = LowerCase(ExistingRecipient) then
                exit;

        Recipients.Add(DelChr(EmailAddress, '<>', ' '));
    end;

    local procedure NormalizeRecipientLists(var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text])
    var
        NewToRecipients: List of [Text];
        NewCCRecipients: List of [Text];
        NewBCCRecipients: List of [Text];
        Recipient: Text;
    begin
        foreach Recipient in ToRecipients do
            AddUniqueRecipient(NewToRecipients, Recipient);

        foreach Recipient in CCRecipients do
            if not IsRecipientInList(NewToRecipients, LowerCase(Recipient)) then
                AddUniqueRecipient(NewCCRecipients, Recipient);

        foreach Recipient in BCCRecipients do
            if not IsRecipientInList(NewToRecipients, LowerCase(Recipient)) and
               not IsRecipientInList(NewCCRecipients, LowerCase(Recipient))
            then
                AddUniqueRecipient(NewBCCRecipients, Recipient);

        ReplaceRecipientList(ToRecipients, NewToRecipients);
        ReplaceRecipientList(CCRecipients, NewCCRecipients);
        ReplaceRecipientList(BCCRecipients, NewBCCRecipients);
    end;

    local procedure ReplaceRecipientList(var TargetRecipients: List of [Text]; SourceRecipients: List of [Text])
    var
        Recipient: Text;
    begin
        Clear(TargetRecipients);
        foreach Recipient in SourceRecipients do
            TargetRecipients.Add(Recipient);
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
