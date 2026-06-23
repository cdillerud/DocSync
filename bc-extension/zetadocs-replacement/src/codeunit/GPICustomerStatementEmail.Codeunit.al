codeunit 70527 "GPI Customer Statement Email"
{
    Permissions =
        tabledata Customer = rm,
        tabledata Contact = r,
        tabledata "Cust. Ledger Entry" = r,
        tabledata "GPI Document Delivery Log" = rimd,
        tabledata "GPI Document Routing Rule" = r;

    procedure GetDefaultDates(var StartDate: Date; var EndDate: Date)
    begin
        EndDate := WorkDate();
        StartDate := CalcDate('<-1M>', EndDate);
    end;

    procedure PreviewStatement(Customer: Record Customer; StartDate: Date; EndDate: Date)
    var
        TempBlob: Codeunit "Temp Blob";
        FileName: Text;
    begin
        ValidateStatement(Customer, StartDate, EndDate);
        GenerateStatementPdf(Customer, StartDate, EndDate, TempBlob);
        FileName := BuildAttachmentName(Customer."No.", EndDate);

        if not File.ViewFromStream(TempBlob.CreateInStream(), FileName, true) then
            File.DownloadFromStream(
                TempBlob.CreateInStream(),
                'Download Customer Statement',
                '',
                'PDF files (*.pdf)|*.pdf',
                FileName);
    end;

    procedure OpenStatementDraft(var Customer: Record Customer; StartDate: Date; EndDate: Date)
    var
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        EmailScenario: Codeunit "Email Scenario";
        EmailAccount: Record "Email Account";
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
        ValidateStatement(Customer, StartDate, EndDate);
        ResolveStatementRecipients(Customer, ToRecipients, CCRecipients, BCCRecipients, AppliedRuleEntries);

        if ToRecipients.Count() = 0 then begin
            UpdateCustomerMissingRecipient(Customer, StartDate, EndDate);
            Commit();
            Error(
                'No statement recipient was found for customer %1. Add an email to the Customer Card primary contact, populate the Customer Card E-Mail field, or create a customer-specific Customer Statement routing rule.',
                Customer."No.");
        end;

        EnsureStatementScenarioAssigned();
        EmailScenario.GetEmailAccount(Enum::"Email Scenario"::"GPI Customer Statement", EmailAccount);
        GenerateStatementPdf(Customer, StartDate, EndDate, TempBlob);

        AttachmentName := CopyStr(BuildAttachmentName(Customer."No.", EndDate), 1, MaxStrLen(AttachmentName));
        Subject := BuildSubject(StartDate, EndDate);
        Body := BuildBody(Customer, StartDate, EndDate);

        EmailMessage.Create(ToRecipients, Subject, Body, true, CCRecipients, BCCRecipients);
        TempBlob.CreateInStream(AttachmentInStream);
        EmailMessage.AddAttachment(AttachmentName, 'application/pdf', AttachmentInStream);
        Email.AddRelation(
            EmailMessage,
            Database::Customer,
            Customer.SystemId,
            Enum::"Email Relation Type"::"Primary Source",
            Enum::"Email Relation Origin"::"Compose Context");

        CreateDeliveryLog(
            DeliveryLog,
            Customer,
            StartDate,
            EndDate,
            DeliveryLog.Status::Created,
            AttachmentName,
            Subject,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries,
            EmailAccount,
            EmailMessage.GetId(),
            TempBlob,
            '',
            false);
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

    procedure SendStatementBatch(var FilteredCustomers: Record Customer; StartDate: Date; EndDate: Date)
    var
        Customer: Record Customer;
        CustomerNos: List of [Code[20]];
        CustomerNo: Code[20];
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedRuleEntries: Text[250];
        ReadyCount: Integer;
        SentCount: Integer;
        FailedCount: Integer;
        MissingRecipientCount: Integer;
        NoActivityCount: Integer;
        AlreadySentCount: Integer;
    begin
        ValidateDates(StartDate, EndDate);
        EnsureStatementScenarioAssigned();
        CollectCustomerNumbers(FilteredCustomers, CustomerNos);

        if CustomerNos.Count() = 0 then
            Error('No customers are included in the current selection or filter.');

        foreach CustomerNo in CustomerNos do
            if Customer.Get(CustomerNo) then
                if not HasStatementData(CustomerNo, StartDate, EndDate) then
                    NoActivityCount += 1
                else
                    if IsStatementAlreadySent(Customer, StartDate, EndDate) then
                        AlreadySentCount += 1
                    else begin
                        Clear(ToRecipients);
                        Clear(CCRecipients);
                        Clear(BCCRecipients);
                        Clear(AppliedRuleEntries);
                        ResolveStatementRecipients(Customer, ToRecipients, CCRecipients, BCCRecipients, AppliedRuleEntries);
                        if ToRecipients.Count() = 0 then begin
                            UpdateCustomerMissingRecipient(Customer, StartDate, EndDate);
                            MissingRecipientCount += 1;
                        end else begin
                            UpdateCustomerReady(Customer, StartDate, EndDate, JoinRecipients(ToRecipients));
                            ReadyCount += 1;
                        end;
                    end;

        if ReadyCount = 0 then begin
            Message(
                'No customer statements are ready to send. Missing recipient: %1. No activity or balance: %2. Already sent for this period: %3.',
                MissingRecipientCount,
                NoActivityCount,
                AlreadySentCount);
            exit;
        end;

        if not Confirm(
            'Send the filtered or selected customer statements now?\Ready to send: %1\Missing recipient: %2\No activity or balance: %3\Already sent and skipped: %4',
            false,
            ReadyCount,
            MissingRecipientCount,
            NoActivityCount,
            AlreadySentCount)
        then
            exit;

        foreach CustomerNo in CustomerNos do
            if Customer.Get(CustomerNo) then
                if HasStatementData(CustomerNo, StartDate, EndDate) and
                   not IsStatementAlreadySent(Customer, StartDate, EndDate)
                then begin
                    Clear(ToRecipients);
                    Clear(CCRecipients);
                    Clear(BCCRecipients);
                    Clear(AppliedRuleEntries);
                    ResolveStatementRecipients(Customer, ToRecipients, CCRecipients, BCCRecipients, AppliedRuleEntries);
                    if ToRecipients.Count() > 0 then
                        if SendOneStatement(Customer, StartDate, EndDate) then
                            SentCount += 1
                        else
                            FailedCount += 1;
                end;

        Message(
            'Customer statement batch complete. Sent: %1. Failed: %2. Missing recipient: %3. No activity or balance: %4. Already sent and skipped: %5.',
            SentCount,
            FailedCount,
            MissingRecipientCount,
            NoActivityCount,
            AlreadySentCount);
    end;

    local procedure SendOneStatement(var Customer: Record Customer; StartDate: Date; EndDate: Date): Boolean
    var
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        EmailScenario: Codeunit "Email Scenario";
        EmailAccount: Record "Email Account";
        DeliveryLog: Record "GPI Document Delivery Log";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AttachmentInStream: InStream;
        AttachmentName: Text[250];
        Subject: Text;
        Body: Text;
        AppliedRuleEntries: Text[250];
        ErrorText: Text;
        SentSuccessfully: Boolean;
    begin
        ResolveStatementRecipients(Customer, ToRecipients, CCRecipients, BCCRecipients, AppliedRuleEntries);
        if ToRecipients.Count() = 0 then begin
            UpdateCustomerMissingRecipient(Customer, StartDate, EndDate);
            exit(false);
        end;

        EmailScenario.GetEmailAccount(Enum::"Email Scenario"::"GPI Customer Statement", EmailAccount);
        AttachmentName := CopyStr(BuildAttachmentName(Customer."No.", EndDate), 1, MaxStrLen(AttachmentName));
        Subject := BuildSubject(StartDate, EndDate);
        Body := BuildBody(Customer, StartDate, EndDate);

        ClearLastError();
        if not TryGenerateStatementPdf(Customer, StartDate, EndDate, TempBlob) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := StrSubstNo('The customer statement for %1 could not be rendered as a PDF.', Customer."No.");

            CreateDeliveryLog(
                DeliveryLog,
                Customer,
                StartDate,
                EndDate,
                DeliveryLog.Status::Failed,
                AttachmentName,
                Subject,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRuleEntries,
                EmailAccount,
                EmptyGuid(),
                TempBlob,
                ErrorText,
                true);
            Commit();
            exit(false);
        end;

        EmailMessage.Create(ToRecipients, Subject, Body, true, CCRecipients, BCCRecipients);
        TempBlob.CreateInStream(AttachmentInStream);
        EmailMessage.AddAttachment(AttachmentName, 'application/pdf', AttachmentInStream);
        Email.AddRelation(
            EmailMessage,
            Database::Customer,
            Customer.SystemId,
            Enum::"Email Relation Type"::"Primary Source",
            Enum::"Email Relation Origin"::"Compose Context");

        CreateDeliveryLog(
            DeliveryLog,
            Customer,
            StartDate,
            EndDate,
            DeliveryLog.Status::Created,
            AttachmentName,
            Subject,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries,
            EmailAccount,
            EmailMessage.GetId(),
            TempBlob,
            '',
            false);
        Commit();

        ClearLastError();
        if not TrySendStatementEmail(EmailMessage, SentSuccessfully) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := 'Business Central returned an error while sending the customer statement email.';
            UpdateDeliveryLogFailed(DeliveryLog, ErrorText);
            Commit();
            exit(false);
        end;

        if not SentSuccessfully then begin
            ErrorText := 'Business Central did not confirm that the customer statement email was sent.';
            UpdateDeliveryLogFailed(DeliveryLog, ErrorText);
            Commit();
            exit(false);
        end;

        UpdateDeliveryLogSent(DeliveryLog, EmailMessage);
        Commit();
        exit(true);
    end;

    local procedure ValidateStatement(Customer: Record Customer; StartDate: Date; EndDate: Date)
    begin
        Customer.TestField("No.");
        ValidateDates(StartDate, EndDate);
        if not HasStatementData(Customer."No.", StartDate, EndDate) then
            Error(
                'Customer %1 has no ledger activity in the selected period and no outstanding balance through %2.',
                Customer."No.",
                EndDate);
    end;

    local procedure ValidateDates(StartDate: Date; EndDate: Date)
    begin
        if StartDate = 0D then
            Error('Enter a statement start date.');
        if EndDate = 0D then
            Error('Enter a statement end date.');
        if EndDate < StartDate then
            Error('The statement end date cannot be before the start date.');
    end;

    local procedure EnsureStatementScenarioAssigned()
    var
        EmailScenario: Codeunit "Email Scenario";
    begin
        if not EmailScenario.IsThereEmailAccountSetForScenario(Enum::"Email Scenario"::"GPI Customer Statement") then
            Error(
                'The GPI Customer Statement email scenario is not assigned to an email account. Open Email Scenario Setup and assign it to the Accounting mailbox before emailing statements.');
    end;

    local procedure GenerateStatementPdf(Customer: Record Customer; StartDate: Date; EndDate: Date; var TempBlob: Codeunit "Temp Blob")
    begin
        if not TryGenerateStatementPdf(Customer, StartDate, EndDate, TempBlob) then
            Error('%1', GetLastErrorText());
    end;

    [TryFunction]
    local procedure TryGenerateStatementPdf(Customer: Record Customer; StartDate: Date; EndDate: Date; var TempBlob: Codeunit "Temp Blob")
    var
        CustomerCopy: Record Customer;
        CustomerRef: RecordRef;
        AttachmentOutStream: OutStream;
    begin
        CustomerCopy.SetRange("No.", Customer."No.");
        CustomerCopy.SetRange("Date Filter", StartDate, EndDate);
        CustomerRef.GetTable(CustomerCopy);
        TempBlob.CreateOutStream(AttachmentOutStream);
        Report.SaveAs(
            Report::"GPI Customer Statement",
            '',
            ReportFormat::Pdf,
            AttachmentOutStream,
            CustomerRef);

        if not TempBlob.HasValue() then
            Error('No PDF was generated for customer statement %1.', Customer."No.");
    end;

    [TryFunction]
    local procedure TryOpenEmailEditor(EmailMessage: Codeunit "Email Message"; EmailAccount: Record "Email Account"; var EmailAction: Enum "Email Action")
    var
        Email: Codeunit Email;
    begin
        EmailAction := Email.OpenInEditorModally(EmailMessage, EmailAccount);
    end;

    [TryFunction]
    local procedure TrySendStatementEmail(EmailMessage: Codeunit "Email Message"; var SentSuccessfully: Boolean)
    var
        Email: Codeunit Email;
    begin
        SentSuccessfully := Email.Send(EmailMessage, Enum::"Email Scenario"::"GPI Customer Statement");
    end;

    local procedure HasStatementData(CustomerNo: Code[20]; StartDate: Date; EndDate: Date): Boolean
    var
        CustLedgerEntry: Record "Cust. Ledger Entry";
    begin
        CustLedgerEntry.SetRange("Customer No.", CustomerNo);
        CustLedgerEntry.SetRange("Posting Date", StartDate, EndDate);
        if not CustLedgerEntry.IsEmpty() then
            exit(true);

        CustLedgerEntry.Reset();
        CustLedgerEntry.SetRange("Customer No.", CustomerNo);
        CustLedgerEntry.SetFilter("Posting Date", '..%1', EndDate);
        if CustLedgerEntry.FindSet() then
            repeat
                CustLedgerEntry.CalcFields("Remaining Amt. (LCY)");
                if CustLedgerEntry."Remaining Amt. (LCY)" <> 0 then
                    exit(true);
            until CustLedgerEntry.Next() = 0;

        exit(false);
    end;

    local procedure IsStatementAlreadySent(Customer: Record Customer; StartDate: Date; EndDate: Date): Boolean
    begin
        exit(
            (Customer."GPI Statement Status" = Customer."GPI Statement Status"::Sent) and
            (Customer."GPI Last Statement Start Date" = StartDate) and
            (Customer."GPI Last Statement End Date" = EndDate));
    end;

    local procedure ResolveStatementRecipients(Customer: Record Customer; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250])
    var
        SpecificRuleApplied: Boolean;
    begin
        SpecificRuleApplied := ApplyStatementRoutingRules(
            Customer,
            true,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries);

        if ToRecipients.Count() = 0 then
            AddRecipientsFromText(ToRecipients, GetPrimaryContactEmail(Customer."Primary Contact No."));

        if ToRecipients.Count() = 0 then
            AddRecipientsFromText(ToRecipients, Customer."E-Mail");

        if not SpecificRuleApplied then
            ApplyStatementRoutingRules(
                Customer,
                false,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRuleEntries);

        NormalizeRecipientLists(ToRecipients, CCRecipients, BCCRecipients);
    end;

    local procedure ApplyStatementRoutingRules(Customer: Record Customer; SpecificCustomerOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250]): Boolean
    var
        RoutingRule: Record "GPI Document Routing Rule";
        RuleApplied: Boolean;
    begin
        RoutingRule.SetCurrentKey(Enabled, "Delivery Document Type", Priority, "Entry No.");
        RoutingRule.SetRange(Enabled, true);
        RoutingRule.SetRange(
            "Delivery Document Type",
            Enum::"GPI Delivery Document Type"::"Customer Statement");

        if not RoutingRule.FindSet() then
            exit(false);

        repeat
            if StatementRoutingRuleMatches(RoutingRule, Customer, SpecificCustomerOnly) and
               RoutingRuleIsActive(RoutingRule, Today)
            then begin
                ApplyRoutingRule(RoutingRule, ToRecipients, CCRecipients, BCCRecipients);
                AppendRoutingRuleEntry(AppliedRuleEntries, RoutingRule."Entry No.");
                RuleApplied := true;
            end;
        until RoutingRule.Next() = 0;

        exit(RuleApplied);
    end;

    local procedure StatementRoutingRuleMatches(RoutingRule: Record "GPI Document Routing Rule"; Customer: Record Customer; SpecificCustomerOnly: Boolean): Boolean
    begin
        if RoutingRule."Vendor No." <> '' then
            exit(false);
        if RoutingRule."Location Code" <> '' then
            exit(false);

        if SpecificCustomerOnly then begin
            if RoutingRule."Customer No." <> Customer."No." then
                exit(false);
        end else
            if RoutingRule."Customer No." <> '' then
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

    local procedure GetPrimaryContactEmail(ContactNo: Code[20]): Text
    var
        Contact: Record Contact;
    begin
        if (ContactNo <> '') and Contact.Get(ContactNo) then
            exit(Contact."E-Mail");
        exit('');
    end;

    local procedure BuildAttachmentName(CustomerNo: Code[20]; EndDate: Date): Text
    begin
        exit(StrSubstNo(
            'Customer-Statement %1 %2.pdf',
            CustomerNo,
            Format(EndDate, 0, '<Year4>-<Month,2>-<Day,2>')));
    end;

    local procedure BuildSubject(StartDate: Date; EndDate: Date): Text
    begin
        exit(StrSubstNo(
            'Customer Statement %1 through %2',
            Format(StartDate, 0, '<Month,2>/<Day,2>/<Year4>'),
            Format(EndDate, 0, '<Month,2>/<Day,2>/<Year4>')));
    end;

    local procedure BuildBody(Customer: Record Customer; StartDate: Date; EndDate: Date): Text
    begin
        exit(StrSubstNo(
            '<p>Hello,</p><p>Please find attached the customer statement for %1 covering %2 through %3.</p><p>Thank you,</p>',
            Customer.Name,
            Format(StartDate, 0, '<Month,2>/<Day,2>/<Year4>'),
            Format(EndDate, 0, '<Month,2>/<Day,2>/<Year4>')));
    end;

    local procedure CreateDeliveryLog(var DeliveryLog: Record "GPI Document Delivery Log"; Customer: Record Customer; StartDate: Date; EndDate: Date; InitialStatus: Enum "GPI Delivery Status"; AttachmentName: Text[250]; Subject: Text; ToRecipients: List of [Text]; CCRecipients: List of [Text]; BCCRecipients: List of [Text]; AppliedRuleEntries: Text[250]; EmailAccount: Record "Email Account"; EmailMessageId: Guid; TempBlob: Codeunit "Temp Blob"; ErrorText: Text; Completed: Boolean)
    var
        DocumentInStream: InStream;
        DocumentOutStream: OutStream;
    begin
        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryLog."Delivery Document Type"::"Customer Statement";
        DeliveryLog.Status := InitialStatus;
        DeliveryLog."Customer No." := Customer."No.";
        DeliveryLog."Report ID" := Report::"GPI Customer Statement";
        DeliveryLog."Attachment Filename" := AttachmentName;
        DeliveryLog."To Recipients" := CopyStr(JoinRecipients(ToRecipients), 1, MaxStrLen(DeliveryLog."To Recipients"));
        DeliveryLog."CC Recipients" := CopyStr(JoinRecipients(CCRecipients), 1, MaxStrLen(DeliveryLog."CC Recipients"));
        DeliveryLog."BCC Recipients" := CopyStr(JoinRecipients(BCCRecipients), 1, MaxStrLen(DeliveryLog."BCC Recipients"));
        DeliveryLog.Subject := CopyStr(Subject, 1, MaxStrLen(DeliveryLog.Subject));
        DeliveryLog."Email Message ID" := EmailMessageId;
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog."Created By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Created By"));
        DeliveryLog."Source Table ID" := Database::Customer;
        DeliveryLog."Source SystemId" := Customer.SystemId;
        DeliveryLog."Source Document Type" := 'Customer Statement';
        DeliveryLog."Source Document No." := Customer."No.";
        DeliveryLog."Source Party Type" := 'Customer';
        DeliveryLog."Source Party No." := Customer."No.";
        DeliveryLog."Statement Start Date" := StartDate;
        DeliveryLog."Statement End Date" := EndDate;
        DeliveryLog."Sender User" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Sender User"));
        DeliveryLog."Sender Email Address" := CopyStr(EmailAccount."Email Address", 1, MaxStrLen(DeliveryLog."Sender Email Address"));
        DeliveryLog."Sender Policy" := 'Email Scenario';
        DeliveryLog."Routing Rule Entry Nos." := AppliedRuleEntries;
        DeliveryLog."Sender Account Name" := CopyStr(EmailAccount.Name, 1, MaxStrLen(DeliveryLog."Sender Account Name"));
        DeliveryLog."Sender Connector" := CopyStr(Format(EmailAccount.Connector), 1, MaxStrLen(DeliveryLog."Sender Connector"));
        DeliveryLog."Sender Account ID" := EmailAccount."Account Id";
        DeliveryLog."Error Message" := CopyStr(ErrorText, 1, MaxStrLen(DeliveryLog."Error Message"));

        if Completed then begin
            DeliveryLog."Completed Date/Time" := CurrentDateTime();
            DeliveryLog."Completed By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Completed By"));
        end;

        DeliveryLog.Insert(true);
        if TempBlob.HasValue() then begin
            TempBlob.CreateInStream(DocumentInStream);
            DeliveryLog."Document Content".CreateOutStream(DocumentOutStream);
            CopyStream(DocumentOutStream, DocumentInStream);
            DeliveryLog.Modify(true);
        end;
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

    local procedure UpdateDeliveryLogSent(var DeliveryLog: Record "GPI Document Delivery Log"; EmailMessage: Codeunit "Email Message")
    begin
        DeliveryLog.Status := DeliveryLog.Status::Sent;
        DeliveryLog."Completed Date/Time" := CurrentDateTime();
        DeliveryLog."Completed By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Completed By"));
        DeliveryLog."External Delivery ID" := CopyStr(EmailMessage.GetExternalId(), 1, MaxStrLen(DeliveryLog."External Delivery ID"));
        Clear(DeliveryLog."Error Message");
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

    local procedure UpdateCustomerReady(var Customer: Record Customer; StartDate: Date; EndDate: Date; RecipientText: Text)
    begin
        Customer."GPI Statement Status" := Customer."GPI Statement Status"::Ready;
        Customer."GPI Statement Recipient" := CopyStr(RecipientText, 1, MaxStrLen(Customer."GPI Statement Recipient"));
        Customer."GPI Last Statement Start Date" := StartDate;
        Customer."GPI Last Statement End Date" := EndDate;
        Clear(Customer."GPI Last Statement Error");
        Customer.Modify(false);
    end;

    local procedure UpdateCustomerMissingRecipient(var Customer: Record Customer; StartDate: Date; EndDate: Date)
    begin
        Customer."GPI Statement Status" := Customer."GPI Statement Status"::"Missing Recipient";
        Clear(Customer."GPI Statement Recipient");
        Customer."GPI Last Statement Start Date" := StartDate;
        Customer."GPI Last Statement End Date" := EndDate;
        Customer."GPI Last Statement Error" := CopyStr(
            StrSubstNo(
                'No statement recipient was found for customer %1. Add an email to the Customer Card primary contact, populate the Customer Card E-Mail field, or create a customer-specific Customer Statement routing rule.',
                Customer."No."),
            1,
            MaxStrLen(Customer."GPI Last Statement Error"));
        Customer.Modify(false);
    end;

    [EventSubscriber(ObjectType::Table, Database::"GPI Document Delivery Log", 'OnAfterModifyEvent', '', false, false)]
    local procedure DeliveryLogOnAfterModify(var Rec: Record "GPI Document Delivery Log"; var xRec: Record "GPI Document Delivery Log"; RunTrigger: Boolean)
    var
        Customer: Record Customer;
    begin
        if Rec."Delivery Document Type" <> Rec."Delivery Document Type"::"Customer Statement" then
            exit;
        if Rec."Source Table ID" <> Database::Customer then
            exit;
        if not Customer.Get(Rec."Source Document No.") then
            exit;

        Customer."GPI Statement Status" := Rec.Status;
        Customer."GPI Statement Recipient" := CopyStr(Rec."To Recipients", 1, MaxStrLen(Customer."GPI Statement Recipient"));
        Customer."GPI Last Statement Entry No." := Rec."Entry No.";
        Customer."GPI Last Statement Date/Time" := Rec."Completed Date/Time";
        Customer."GPI Last Statement Error" := CopyStr(Rec."Error Message", 1, MaxStrLen(Customer."GPI Last Statement Error"));
        Customer."GPI Last Statement Sender" := CopyStr(Rec."Sender Email Address", 1, MaxStrLen(Customer."GPI Last Statement Sender"));
        Customer."GPI Last Statement Start Date" := Rec."Statement Start Date";
        Customer."GPI Last Statement End Date" := Rec."Statement End Date";
        Customer.Modify(false);
    end;

    local procedure CollectCustomerNumbers(var FilteredCustomers: Record Customer; var CustomerNos: List of [Code[20]])
    var
        CustomerCopy: Record Customer;
    begin
        CustomerCopy.Copy(FilteredCustomers);
        if CustomerCopy.FindSet() then
            repeat
                CustomerNos.Add(CustomerCopy."No.");
            until CustomerCopy.Next() = 0;
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

    local procedure EmptyGuid(): Guid
    var
        Result: Guid;
    begin
        exit(Result);
    end;
}
