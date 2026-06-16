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

        OpenSalesDocumentDraft(SalesHeader, 50020, Subject, Body, AttachmentName);
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

        OpenSalesDocumentDraft(SalesHeader, 50003, Subject, Body, AttachmentName);
    end;

    local procedure OpenSalesDocumentDraft(var SalesHeader: Record "Sales Header"; ReportId: Integer; Subject: Text; Body: Text; AttachmentName: Text[250])
    var
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        SalesHeaderRef: RecordRef;
        AttachmentOutStream: OutStream;
        AttachmentInStream: InStream;
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        RecipientEmail: Text;
        SalespersonEmail: Text;
        InsideSalespersonCode: Code[20];
        InsideSalespersonEmail: Text;
        CurrentUserEmail: Text;
        RequestPageParameters: Text;
    begin
        SalesHeader.TestField("Document Type", SalesHeader."Document Type"::Order);
        SalesHeader.TestField("No.");
        SalesHeader.TestField("Sell-to Customer No.");

        RecipientEmail := GetRecipientEmail(SalesHeader);
        if RecipientEmail = '' then
            Error(
                'Sales Order %1 does not have a recipient email address. Add an email to the Sell-to Contact, the Sales Order, or customer %2.',
                SalesHeader."No.",
                SalesHeader."Sell-to Customer No.");

        ToRecipients.Add(RecipientEmail);
        CurrentUserEmail := UserId();

        SalespersonEmail := GetSalespersonEmail(SalesHeader."Salesperson Code");
        AddCcRecipient(CCRecipients, SalespersonEmail, RecipientEmail, CurrentUserEmail);

        InsideSalespersonCode := GetInsideSalespersonCode(SalesHeader);
        InsideSalespersonEmail := GetSalespersonEmail(InsideSalespersonCode);
        AddCcRecipient(CCRecipients, InsideSalespersonEmail, RecipientEmail, CurrentUserEmail);

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

    local procedure GetRecipientEmail(SalesHeader: Record "Sales Header"): Text
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

    local procedure AddCcRecipient(var CCRecipients: List of [Text]; EmailAddress: Text; ToAddress: Text; SenderAddress: Text)
    var
        ExistingRecipient: Text;
        NormalizedEmail: Text;
    begin
        NormalizedEmail := LowerCase(EmailAddress);
        if NormalizedEmail = '' then
            exit;

        if NormalizedEmail = LowerCase(ToAddress) then
            exit;

        if NormalizedEmail = LowerCase(SenderAddress) then
            exit;

        foreach ExistingRecipient in CCRecipients do
            if NormalizedEmail = LowerCase(ExistingRecipient) then
                exit;

        CCRecipients.Add(EmailAddress);
    end;
}
