codeunit 70511 "GPI Invoice Batch Email"
{
    Permissions =
        tabledata "Sales Invoice Header" = rm,
        tabledata "GPI Document Delivery Log" = rimd,
        tabledata "GPI Document Routing Rule" = r;

    procedure RefreshQueue(var FilteredInvoices: Record "Sales Invoice Header")
    var
        SalesInvoiceHeader: Record "Sales Invoice Header";
        InvoiceNos: List of [Code[20]];
        InvoiceNo: Code[20];
    begin
        CollectInvoiceNumbers(FilteredInvoices, InvoiceNos);
        foreach InvoiceNo in InvoiceNos do
            if SalesInvoiceHeader.Get(InvoiceNo) then
                RefreshInvoiceStatus(SalesInvoiceHeader);
    end;

    procedure SendInvoices(var FilteredInvoices: Record "Sales Invoice Header")
    var
        SalesInvoiceHeader: Record "Sales Invoice Header";
        EmailScenario: Codeunit "Email Scenario";
        InvoiceNos: List of [Code[20]];
        InvoiceNo: Code[20];
        ReadyCount: Integer;
        MissingRecipientCount: Integer;
        AlreadySentCount: Integer;
        SentCount: Integer;
        FailedCount: Integer;
    begin
        CollectInvoiceNumbers(FilteredInvoices, InvoiceNos);
        if InvoiceNos.Count() = 0 then
            Error('No posted sales invoices are included in the current selection or filter.');

        foreach InvoiceNo in InvoiceNos do
            if SalesInvoiceHeader.Get(InvoiceNo) then begin
                RefreshInvoiceStatus(SalesInvoiceHeader);
                case SalesInvoiceHeader."GPI Invoice Delivery Status" of
                    SalesInvoiceHeader."GPI Invoice Delivery Status"::Ready:
                        ReadyCount += 1;
                    SalesInvoiceHeader."GPI Invoice Delivery Status"::"Missing Recipient":
                        MissingRecipientCount += 1;
                    SalesInvoiceHeader."GPI Invoice Delivery Status"::Sent:
                        AlreadySentCount += 1;
                end;
            end;

        if ReadyCount = 0 then begin
            Message(
                'No invoices are ready to send. Missing recipient: %1. Already sent: %2.',
                MissingRecipientCount,
                AlreadySentCount);
            exit;
        end;

        if not EmailScenario.IsThereEmailAccountSetForScenario(Enum::"Email Scenario"::"GPI Invoice Batch") then
            Error(
                'The GPI Invoice Batch email scenario is not assigned to an email account. Open Email Scenario Setup and assign GPI Invoice Batch to the Accounting invoice mailbox before sending.');

        if not Confirm(
            'Send the filtered or selected invoice batch now?\Ready to send: %1\Missing recipient: %2\Already sent and skipped: %3',
            false,
            ReadyCount,
            MissingRecipientCount,
            AlreadySentCount)
        then
            exit;

        foreach InvoiceNo in InvoiceNos do
            if SalesInvoiceHeader.Get(InvoiceNo) then
                if SalesInvoiceHeader."GPI Invoice Delivery Status" = SalesInvoiceHeader."GPI Invoice Delivery Status"::Ready then
                    if SendOneInvoice(SalesInvoiceHeader) then
                        SentCount += 1
                    else
                        FailedCount += 1;

        Message(
            'Invoice batch complete. Sent: %1. Failed: %2. Missing recipient: %3. Already sent and skipped: %4.',
            SentCount,
            FailedCount,
            MissingRecipientCount,
            AlreadySentCount);
    end;

    procedure PreviewInvoice(SalesInvoiceHeader: Record "Sales Invoice Header")
    var
        TempBlob: Codeunit "Temp Blob";
        FileName: Text;
        ErrorText: Text;
    begin
        if not TryGenerateInvoicePdf(SalesInvoiceHeader, TempBlob) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := StrSubstNo('Invoice %1 could not be rendered as a PDF.', SalesInvoiceHeader."No.");
            Error('%1', ErrorText);
        end;

        FileName := StrSubstNo('Invoice %1.pdf', SalesInvoiceHeader."No.");
        if not File.ViewFromStream(TempBlob.CreateInStream(), FileName, true) then
            File.DownloadFromStream(TempBlob.CreateInStream(), 'Download Invoice', '', 'PDF files (*.pdf)|*.pdf', FileName);
    end;

    local procedure SendOneInvoice(var SalesInvoiceHeader: Record "Sales Invoice Header"): Boolean
    var
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        EmailScenario: Codeunit "Email Scenario";
        EmailAccount: Record "Email Account";
        Customer: Record Customer;
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
        ResolveInvoiceRecipients(SalesInvoiceHeader, ToRecipients, CCRecipients, BCCRecipients, AppliedRuleEntries);
        if ToRecipients.Count() = 0 then begin
            UpdateInvoiceHeaderMissingRecipient(SalesInvoiceHeader);
            exit(false);
        end;

        EmailScenario.GetEmailAccount(Enum::"Email Scenario"::"GPI Invoice Batch", EmailAccount);
        AttachmentName := CopyStr(StrSubstNo('Invoice %1.pdf', SalesInvoiceHeader."No."), 1, MaxStrLen(AttachmentName));
        Subject := StrSubstNo('Invoice %1', SalesInvoiceHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Please find attached Invoice %1.</p><p>Thank you,</p>',
            SalesInvoiceHeader."No.");

        if not TryGenerateInvoicePdf(SalesInvoiceHeader, TempBlob) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := StrSubstNo('Invoice %1 could not be rendered as a PDF.', SalesInvoiceHeader."No.");

            CreateInvoiceDeliveryLog(
                DeliveryLog,
                SalesInvoiceHeader,
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
            UpdateInvoiceHeaderFailed(SalesInvoiceHeader, DeliveryLog, ErrorText, EmailAccount."Email Address");
            Commit();
            exit(false);
        end;

        EmailMessage.Create(ToRecipients, Subject, Body, true, CCRecipients, BCCRecipients);
        TempBlob.CreateInStream(AttachmentInStream);
        EmailMessage.AddAttachment(AttachmentName, 'application/pdf', AttachmentInStream);
        Email.AddRelation(
            EmailMessage,
            Database::"Sales Invoice Header",
            SalesInvoiceHeader.SystemId,
            Enum::"Email Relation Type"::"Primary Source",
            Enum::"Email Relation Origin"::"Compose Context");

        if Customer.Get(SalesInvoiceHeader."Bill-to Customer No.") then
            Email.AddRelation(
                EmailMessage,
                Database::Customer,
                Customer.SystemId,
                Enum::"Email Relation Type"::"Related Entity",
                Enum::"Email Relation Origin"::"Compose Context");

        CreateInvoiceDeliveryLog(
            DeliveryLog,
            SalesInvoiceHeader,
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

        if not TrySendInvoiceEmail(EmailMessage, SentSuccessfully) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := 'Business Central returned an error while sending the invoice email.';
            MarkInvoiceFailed(SalesInvoiceHeader, DeliveryLog, ErrorText, EmailAccount."Email Address");
            exit(false);
        end;

        if not SentSuccessfully then begin
            ErrorText := 'Business Central did not confirm that the invoice email was sent.';
            MarkInvoiceFailed(SalesInvoiceHeader, DeliveryLog, ErrorText, EmailAccount."Email Address");
            exit(false);
        end;

        UpdateDeliveryLogSent(DeliveryLog, EmailMessage);
        UpdateInvoiceHeaderSent(SalesInvoiceHeader, DeliveryLog, JoinRecipients(ToRecipients), EmailAccount."Email Address");
        Commit();
        exit(true);
    end;

    local procedure MarkInvoiceFailed(var SalesInvoiceHeader: Record "Sales Invoice Header"; var DeliveryLog: Record "GPI Document Delivery Log"; ErrorText: Text; SenderEmail: Text)
    begin
        UpdateDeliveryLogFailed(DeliveryLog, ErrorText);
        UpdateInvoiceHeaderFailed(SalesInvoiceHeader, DeliveryLog, ErrorText, SenderEmail);
        Commit();
    end;

    [TryFunction]
    local procedure TryGenerateInvoicePdf(SalesInvoiceHeader: Record "Sales Invoice Header"; var TempBlob: Codeunit "Temp Blob")
    var
        ReportSelections: Record "Report Selections";
    begin
        SalesInvoiceHeader.SetRecFilter();
        ReportSelections.GetPdfReportForCust(
            TempBlob,
            ReportSelections.Usage::"S.Invoice",
            SalesInvoiceHeader,
            SalesInvoiceHeader."Bill-to Customer No.");

        if not TempBlob.HasValue() then
            Error(
                'No PDF was generated for posted sales invoice %1. Check Report Selection - Sales for usage S.Invoice.',
                SalesInvoiceHeader."No.");
    end;

    [TryFunction]
    local procedure TrySendInvoiceEmail(EmailMessage: Codeunit "Email Message"; var SentSuccessfully: Boolean)
    var
        Email: Codeunit Email;
    begin
        SentSuccessfully := Email.Send(EmailMessage, Enum::"Email Scenario"::"GPI Invoice Batch");
    end;

    local procedure RefreshInvoiceStatus(var SalesInvoiceHeader: Record "Sales Invoice Header")
    var
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedRuleEntries: Text[250];
    begin
        ResolveInvoiceRecipients(SalesInvoiceHeader, ToRecipients, CCRecipients, BCCRecipients, AppliedRuleEntries);
        SalesInvoiceHeader."GPI Invoice Recipient" := CopyStr(
            JoinRecipients(ToRecipients),
            1,
            MaxStrLen(SalesInvoiceHeader."GPI Invoice Recipient"));

        if SalesInvoiceHeader."GPI Invoice Delivery Status" <> SalesInvoiceHeader."GPI Invoice Delivery Status"::Sent then
            if ToRecipients.Count() = 0 then
                SalesInvoiceHeader."GPI Invoice Delivery Status" := SalesInvoiceHeader."GPI Invoice Delivery Status"::"Missing Recipient"
            else begin
                SalesInvoiceHeader."GPI Invoice Delivery Status" := SalesInvoiceHeader."GPI Invoice Delivery Status"::Ready;
                Clear(SalesInvoiceHeader."GPI Last Delivery Error");
            end;

        SalesInvoiceHeader.Modify(false);
    end;

    local procedure ResolveInvoiceRecipients(SalesInvoiceHeader: Record "Sales Invoice Header"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250])
    var
        DocumentPolicy: Codeunit "GPI Document Policy Mgt.";
    begin
        DocumentPolicy.ResolvePostedInvoiceRecipients(
            SalesInvoiceHeader,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries);
    end;

    local procedure CreateInvoiceDeliveryLog(var DeliveryLog: Record "GPI Document Delivery Log"; SalesInvoiceHeader: Record "Sales Invoice Header"; InitialStatus: Enum "GPI Delivery Status"; AttachmentName: Text[250]; Subject: Text; ToRecipients: List of [Text]; CCRecipients: List of [Text]; BCCRecipients: List of [Text]; AppliedRuleEntries: Text[250]; EmailAccount: Record "Email Account"; EmailMessageId: Guid; TempBlob: Codeunit "Temp Blob"; ErrorText: Text; Completed: Boolean)
    var
        DocumentInStream: InStream;
        DocumentOutStream: OutStream;
    begin
        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryLog."Delivery Document Type"::Invoice;
        DeliveryLog.Status := InitialStatus;
        DeliveryLog."Customer No." := SalesInvoiceHeader."Bill-to Customer No.";
        DeliveryLog."Location Code" := SalesInvoiceHeader."Location Code";
        DeliveryLog."Attachment Filename" := AttachmentName;
        DeliveryLog."To Recipients" := CopyStr(JoinRecipients(ToRecipients), 1, MaxStrLen(DeliveryLog."To Recipients"));
        DeliveryLog."CC Recipients" := CopyStr(JoinRecipients(CCRecipients), 1, MaxStrLen(DeliveryLog."CC Recipients"));
        DeliveryLog."BCC Recipients" := CopyStr(JoinRecipients(BCCRecipients), 1, MaxStrLen(DeliveryLog."BCC Recipients"));
        DeliveryLog.Subject := CopyStr(Subject, 1, MaxStrLen(DeliveryLog.Subject));
        DeliveryLog."Email Message ID" := EmailMessageId;
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog."Created By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Created By"));
        DeliveryLog."Source Table ID" := Database::"Sales Invoice Header";
        DeliveryLog."Source SystemId" := SalesInvoiceHeader.SystemId;
        DeliveryLog."Source Document Type" := 'Posted Sales Invoice';
        DeliveryLog."Source Document No." := SalesInvoiceHeader."No.";
        DeliveryLog."Source Party Type" := 'Customer';
        DeliveryLog."Source Party No." := SalesInvoiceHeader."Bill-to Customer No.";
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

    local procedure UpdateInvoiceHeaderSent(var SalesInvoiceHeader: Record "Sales Invoice Header"; DeliveryLog: Record "GPI Document Delivery Log"; RecipientText: Text; SenderEmail: Text)
    begin
        SalesInvoiceHeader."GPI Invoice Delivery Status" := SalesInvoiceHeader."GPI Invoice Delivery Status"::Sent;
        SalesInvoiceHeader."GPI Invoice Recipient" := CopyStr(RecipientText, 1, MaxStrLen(SalesInvoiceHeader."GPI Invoice Recipient"));
        SalesInvoiceHeader."GPI Last Delivery Entry No." := DeliveryLog."Entry No.";
        SalesInvoiceHeader."GPI Last Delivery Date/Time" := DeliveryLog."Completed Date/Time";
        SalesInvoiceHeader."GPI Last Sender Email" := CopyStr(SenderEmail, 1, MaxStrLen(SalesInvoiceHeader."GPI Last Sender Email"));
        Clear(SalesInvoiceHeader."GPI Last Delivery Error");
        SalesInvoiceHeader.Modify(false);
    end;

    local procedure UpdateInvoiceHeaderFailed(var SalesInvoiceHeader: Record "Sales Invoice Header"; DeliveryLog: Record "GPI Document Delivery Log"; ErrorText: Text; SenderEmail: Text)
    begin
        SalesInvoiceHeader."GPI Invoice Delivery Status" := SalesInvoiceHeader."GPI Invoice Delivery Status"::Failed;
        SalesInvoiceHeader."GPI Last Delivery Entry No." := DeliveryLog."Entry No.";
        SalesInvoiceHeader."GPI Last Delivery Date/Time" := DeliveryLog."Completed Date/Time";
        SalesInvoiceHeader."GPI Last Sender Email" := CopyStr(SenderEmail, 1, MaxStrLen(SalesInvoiceHeader."GPI Last Sender Email"));
        SalesInvoiceHeader."GPI Last Delivery Error" := CopyStr(ErrorText, 1, MaxStrLen(SalesInvoiceHeader."GPI Last Delivery Error"));
        SalesInvoiceHeader.Modify(false);
    end;

    local procedure UpdateInvoiceHeaderMissingRecipient(var SalesInvoiceHeader: Record "Sales Invoice Header")
    begin
        SalesInvoiceHeader."GPI Invoice Delivery Status" := SalesInvoiceHeader."GPI Invoice Delivery Status"::"Missing Recipient";
        Clear(SalesInvoiceHeader."GPI Invoice Recipient");
        SalesInvoiceHeader."GPI Last Delivery Error" := CopyStr(
            StrSubstNo(
                'No invoice recipient was found for customer %1. Add an email to the Customer Card primary contact or create a customer-specific Invoice routing rule.',
                SalesInvoiceHeader."Bill-to Customer No."),
            1,
            MaxStrLen(SalesInvoiceHeader."GPI Last Delivery Error"));
        SalesInvoiceHeader.Modify(false);
    end;

    local procedure CollectInvoiceNumbers(var FilteredInvoices: Record "Sales Invoice Header"; var InvoiceNos: List of [Code[20]])
    var
        InvoiceCopy: Record "Sales Invoice Header";
    begin
        InvoiceCopy.Copy(FilteredInvoices);
        if InvoiceCopy.FindSet() then
            repeat
                InvoiceNos.Add(InvoiceCopy."No.");
            until InvoiceCopy.Next() = 0;
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
