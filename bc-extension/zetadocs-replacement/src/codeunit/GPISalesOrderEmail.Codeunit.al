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
            Report::"GPI Pick Ticket",
            Subject,
            Body,
            AttachmentName,
            ToRecipients);
    end;

    local procedure OpenSalesDocumentDraft(var SalesHeader: Record "Sales Header"; ReportId: Integer; Subject: Text; Body: Text; AttachmentName: Text[250]; var ToRecipients: List of [Text])
    var
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        SalesHeaderRef: RecordRef;
        AttachmentOutStream: OutStream;
        AttachmentInStream: InStream;
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        SalespersonEmail: Text;
        InsideSalespersonCode: Code[20];
        InsideSalespersonEmail: Text;
        CurrentUserEmail: Text;
        RequestPageParameters: Text;
    begin
        SalesHeader.TestField("Document Type", SalesHeader."Document Type"::Order);
        SalesHeader.TestField("No.");
        SalesHeader.TestField("Sell-to Customer No.");

        if ToRecipients.Count() = 0 then
            Error('No email recipients were resolved for Sales Order %1.', SalesHeader."No.");

        CurrentUserEmail := UserId();

        SalespersonEmail := GetSalespersonEmail(SalesHeader."Salesperson Code");
        AddCcRecipient(CCRecipients, SalespersonEmail, ToRecipients, CurrentUserEmail);

        InsideSalespersonCode := GetInsideSalespersonCode(SalesHeader);
        InsideSalespersonEmail := GetSalespersonEmail(InsideSalespersonCode);
        AddCcRecipient(CCRecipients, InsideSalespersonEmail, ToRecipients, CurrentUserEmail);

        EmailMessage.Create(ToRecipients, Subject, Body, true, CCRecipients, BCCRecipients);

        SalesHeader.SetRecFilter();
        SalesHeaderRef.GetTable(SalesHeader);

        Commit();
        RequestPageParameters := Report.RunRequestPage(ReportId);
        if RequestPageParameters = '' then
            exit;

        TempBlob.CreateOutStream(AttachmentOutStream);
        Report.SaveAs(ReportId, RequestPageParameters, ReportFormat::Pdf, AttachmentOutStream, SalesHeaderRef);

        TempBlob.CreateInStream(AttachmentInStream);
        EmailMessage.AddAttachment(AttachmentName, 'application/pdf', AttachmentInStream);

        Email.OpenInEditorModally(EmailMessage);
    end;

    local procedure BuildCustomerRecipients(SalesHeader: Record "Sales Header"; var ToRecipients: List of [Text])
    var
        RecipientText: Text;
    begin
        RecipientText := GetCustomerRecipientText(SalesHeader);
        if RecipientText = '' then
            Error(
                'Sales Order %1 does not have a recipient email address. Add an email to the Sell-to Contact, the Sales Order, or customer %2.',
                SalesHeader."No.",
                SalesHeader."Sell-to Customer No.");

        AddRecipientsFromText(ToRecipients, RecipientText);
    end;

    local procedure BuildLocationRecipients(SalesHeader: Record "Sales Header"; var ToRecipients: List of [Text])
    var
        Location: Record Location;
    begin
        SalesHeader.TestField("Location Code");

        if not Location.Get(SalesHeader."Location Code") then
            Error('Location %1 could not be found for Sales Order %2.', SalesHeader."Location Code", SalesHeader."No.");

        if Location."E-Mail" = '' then
            Error('Location %1 does not have an email address for Sales Order %2.', SalesHeader."Location Code", SalesHeader."No.");

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

            if IsInsideSalespersonField(CandidateName, CandidateCaption) then begin
                CandidateValue := Format(CandidateField);
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
}
