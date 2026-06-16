codeunit 70151000 "GPI Sales Order Email"
{
    procedure OpenSalesOrderConfirmationDraft(var SalesHeader: Record "Sales Header")
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
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        SalesHeader.TestField("Document Type", SalesHeader."Document Type"::Order);
        SalesHeader.TestField("No.");

        RecipientEmail := GetRecipientEmail(SalesHeader);
        if RecipientEmail = '' then
            Error(
                'Sales Order %1 does not have a recipient email address. Enter the Sell-to Email on the order or an email address on customer %2.',
                SalesHeader."No.",
                SalesHeader."Sell-to Customer No.");

        ToRecipients.Add(RecipientEmail);

        SalespersonEmail := GetSalespersonEmail(SalesHeader."Salesperson Code");
        if (SalespersonEmail <> '') and (LowerCase(SalespersonEmail) <> LowerCase(RecipientEmail)) then
            CCRecipients.Add(SalespersonEmail);

        Subject := StrSubstNo('Sales Order Confirmation %1', SalesHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Please find attached Sales Order Confirmation %1.</p><p>Thank you,</p>',
            SalesHeader."No.");

        EmailMessage.Create(ToRecipients, Subject, Body, true, CCRecipients, BCCRecipients);

        TempBlob.CreateOutStream(AttachmentOutStream);
        SalesHeaderRef.GetTable(SalesHeader);
        if not Report.SaveAs(50020, '', ReportFormat::Pdf, AttachmentOutStream, SalesHeaderRef) then
            Error('Business Central could not generate report 50020 for Sales Order %1.', SalesHeader."No.");

        TempBlob.CreateInStream(AttachmentInStream);
        AttachmentName := CopyStr(StrSubstNo('Sales-Order %1.pdf', SalesHeader."No."), 1, MaxStrLen(AttachmentName));
        EmailMessage.AddAttachment(AttachmentName, 'application/pdf', AttachmentInStream);

        Email.OpenInEditor(EmailMessage);
    end;

    local procedure GetRecipientEmail(SalesHeader: Record "Sales Header"): Text
    var
        Customer: Record Customer;
    begin
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
}
