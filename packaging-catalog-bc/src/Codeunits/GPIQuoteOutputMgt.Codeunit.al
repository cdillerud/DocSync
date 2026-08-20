codeunit 71103 "GPI Quote Output Mgt"
{
    procedure PreviewCustomerQuote(QuoteHeader: Record "GPI Pack Quote")
    var
        QuoteToPrint: Record "GPI Pack Quote";
    begin
        EnsureApproved(QuoteHeader);
        QuoteToPrint := QuoteHeader;
        QuoteToPrint.SetRecFilter();
        Report.RunModal(Report::"GPI Pack Quote Rpt", true, false, QuoteToPrint);
    end;

    procedure DownloadCustomerQuotePdf(QuoteHeader: Record "GPI Pack Quote")
    var
        TempBlob: Codeunit "Temp Blob";
        InStr: InStream;
        FileName: Text;
    begin
        CreateCustomerQuotePdf(QuoteHeader, TempBlob, FileName);
        TempBlob.CreateInStream(InStr);

        if not DownloadFromStream(InStr, '', '', '', FileName) then
            Error('The customer quote PDF could not be downloaded.');
    end;

    procedure CreateCustomerQuotePdf(QuoteHeader: Record "GPI Pack Quote"; var TempBlob: Codeunit "Temp Blob"; var FileName: Text)
    var
        QuoteToPrint: Record "GPI Pack Quote";
        RecRef: RecordRef;
        OutStr: OutStream;
    begin
        EnsureApproved(QuoteHeader);

        QuoteToPrint := QuoteHeader;
        QuoteToPrint.SetRecFilter();
        RecRef.GetTable(QuoteToPrint);

        Clear(TempBlob);
        TempBlob.CreateOutStream(OutStr);
        Report.SaveAs(Report::"GPI Pack Quote Rpt", '', ReportFormat::Pdf, OutStr, RecRef);
        FileName := StrSubstNo('Gamer-Packaging-Quote-%1.pdf', QuoteHeader."Entry No.");
    end;

    local procedure EnsureApproved(QuoteHeader: Record "GPI Pack Quote")
    begin
        QuoteHeader.TestField("Entry No.");
        QuoteHeader.TestField("Customer No.");
        if QuoteHeader.Status <> "GPI Pack Quote Stat"::Approved then
            Error('Approve the packaging quote before generating a customer-facing quote document.');
    end;
}
