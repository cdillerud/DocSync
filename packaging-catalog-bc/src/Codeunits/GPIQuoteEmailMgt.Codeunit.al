codeunit 71104 "GPI Quote Email Mgt"
{
    procedure PrepareCustomerQuoteEmail(QuoteHeader: Record "GPI Pack Quote")
    var
        Customer: Record Customer;
        QuoteOutputMgt: Codeunit "GPI Quote Output Mgt";
        DocumentMailing: Codeunit "Document-Mailing";
        PdfBlob: Codeunit "Temp Blob";
        BodyBlob: Codeunit "Temp Blob";
        PdfInStr: InStream;
        BodyOutStr: OutStream;
        AttachmentName: Text;
        Subject: Text;
        BodyText: Text;
    begin
        EnsureApproved(QuoteHeader);

        Customer.Get(QuoteHeader."Customer No.");
        Customer.TestField("E-Mail");

        QuoteOutputMgt.CreateCustomerQuotePdf(QuoteHeader, PdfBlob, AttachmentName);
        PdfBlob.CreateInStream(PdfInStr);

        Subject := StrSubstNo('Gamer Packaging Quote %1', QuoteHeader."Entry No.");
        BodyText := BuildEmailBody(QuoteHeader);
        BodyBlob.CreateOutStream(BodyOutStr);
        BodyOutStr.WriteText(BodyText);

        if not DocumentMailing.EmailFile(
            PdfInStr,
            AttachmentName,
            BodyBlob,
            Subject,
            Customer."E-Mail",
            false,
            "Email Scenario"::"Sales Quote")
        then
            Error('The customer quote email could not be prepared.');
    end;

    local procedure BuildEmailBody(QuoteHeader: Record "GPI Pack Quote"): Text
    var
        BodyText: Text;
    begin
        BodyText := '<p>Hello,</p>';
        BodyText += StrSubstNo('<p>Please find attached Gamer Packaging quote %1.</p>', QuoteHeader."Entry No.");

        if QuoteHeader."Expiration Date" <> 0D then
            BodyText += StrSubstNo('<p>This quote is valid through %1.</p>', Format(QuoteHeader."Expiration Date", 0, '<Month,2>/<Day,2>/<Year4>'));

        BodyText += '<p>Please let us know if you have any questions or would like to discuss the quote.</p>';
        BodyText += '<p>Thank you,<br/>Gamer Packaging</p>';
        exit(BodyText);
    end;

    local procedure EnsureApproved(QuoteHeader: Record "GPI Pack Quote")
    begin
        QuoteHeader.TestField("Entry No.");
        QuoteHeader.TestField("Customer No.");
        if QuoteHeader.Status <> "GPI Pack Quote Stat"::Approved then
            Error('Approve the packaging quote before preparing a customer email.');
    end;
}
