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
        QuoteToPrint: Record "GPI Pack Quote";
        TempBlob: Codeunit "Temp Blob";
        RecRef: RecordRef;
        OutStr: OutStream;
        InStr: InStream;
        FileName: Text;
    begin
        EnsureApproved(QuoteHeader);

        QuoteToPrint := QuoteHeader;
        QuoteToPrint.SetRecFilter();
        RecRef.GetTable(QuoteToPrint);

        TempBlob.CreateOutStream(OutStr);
        Report.SaveAs(Report::"GPI Pack Quote Rpt", '', ReportFormat::Pdf, OutStr, RecRef);
        TempBlob.CreateInStream(InStr);

        FileName := StrSubstNo('Gamer-Packaging-Quote-%1.pdf', QuoteHeader."Entry No.");
        if not DownloadFromStream(InStr, '', '', '', FileName) then
            Error('The customer quote PDF could not be downloaded.');
    end;

    local procedure EnsureApproved(QuoteHeader: Record "GPI Pack Quote")
    begin
        QuoteHeader.TestField("Entry No.");
        QuoteHeader.TestField("Customer No.");
        if QuoteHeader.Status <> "GPI Pack Quote Stat"::Approved then
            Error('Approve the packaging quote before generating a customer-facing quote document.');
    end;
}
