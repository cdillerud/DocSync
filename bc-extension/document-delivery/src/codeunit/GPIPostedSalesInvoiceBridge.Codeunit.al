codeunit 70150005 "GPI Posted Sales Inv Bridge"
{
    Access = Internal;

    procedure SendPostedSalesInvoiceTestEvent(var SalesInvoiceHeader: Record "Sales Invoice Header") Success: Boolean
    var
        Setup: Record "GPI Doc Delivery Setup";
        Builder: Codeunit "GPI Hub Event Builder";
        Client: Codeunit "GPI Hub Client";
        Payload: Text;
        EventId: Text[100];
        CorrelationId: Text[100];
        RecordId: Text[100];
        RecordSystemId: Text[100];
        FileName: Text[250];
        Subject: Text[250];
        RecipientsCsv: Text[1000];
    begin
        GetSetup(Setup);

        if SalesInvoiceHeader."No." = '' then
            Error('A posted sales invoice number is required.');

        EventId := MakeStableId('posted-sales-invoice-test-' + SalesInvoiceHeader."No.");
        CorrelationId := MakeStableId('posted-sales-invoice-' + SalesInvoiceHeader."No.");
        RecordId := CopyStr(Format(SalesInvoiceHeader.RecordId(), 0, 9), 1, MaxStrLen(RecordId));
        RecordSystemId := CopyStr(Format(SalesInvoiceHeader.SystemId), 1, MaxStrLen(RecordSystemId));
        FileName := CopyStr(SalesInvoiceHeader."No." + '.pdf', 1, MaxStrLen(FileName));
        Subject := CopyStr('Posted Sales Invoice ' + SalesInvoiceHeader."No.", 1, MaxStrLen(Subject));
        RecipientsCsv := ResolveRecipient(SalesInvoiceHeader);

        Payload := Builder.BuildDeliverySentPayload(
            Setup,
            EventId,
            CorrelationId,
            'Posted Sales Invoice',
            RecordId,
            SalesInvoiceHeader."No.",
            RecordSystemId,
            'SALES_INVOICE',
            FileName,
            Subject,
            RecipientsCsv);

        Success := Client.SendDeliverySentEvent(
            Payload,
            EventId,
            CorrelationId,
            'Posted Sales Invoice',
            SalesInvoiceHeader."No.",
            'SALES_INVOICE',
            FileName);

        exit(Success);
    end;

    procedure SendPostedSalesInvoiceDocumentLinkEvent(var SalesInvoiceHeader: Record "Sales Invoice Header") Success: Boolean
    var
        Setup: Record "GPI Doc Delivery Setup";
        Builder: Codeunit "GPI Hub Event Builder";
        Client: Codeunit "GPI Hub Client";
        Payload: Text;
        EventId: Text[100];
        CorrelationId: Text[100];
        RecordId: Text[100];
        RecordSystemId: Text[100];
        FileName: Text[250];
        Subject: Text[250];
        RecipientsCsv: Text[1000];
    begin
        GetSetup(Setup);

        if SalesInvoiceHeader."No." = '' then
            Error('A posted sales invoice number is required.');

        if Setup."Document Link Template" = '' then
            Error('Document Link Template must be configured before sending a GPI Hub document link event.');

        EventId := MakeStableId('posted-sales-invoice-document-link-' + SalesInvoiceHeader."No.");
        CorrelationId := MakeStableId('posted-sales-invoice-document-link-' + SalesInvoiceHeader."No.");
        RecordId := CopyStr(Format(SalesInvoiceHeader.RecordId(), 0, 9), 1, MaxStrLen(RecordId));
        RecordSystemId := CopyStr(Format(SalesInvoiceHeader.SystemId), 1, MaxStrLen(RecordSystemId));
        FileName := CopyStr(SalesInvoiceHeader."No." + '.pdf', 1, MaxStrLen(FileName));
        Subject := CopyStr('Posted Sales Invoice Document Link ' + SalesInvoiceHeader."No.", 1, MaxStrLen(Subject));
        RecipientsCsv := ResolveRecipient(SalesInvoiceHeader);

        Payload := Builder.BuildDeliverySentPayload(
            Setup,
            EventId,
            CorrelationId,
            'Posted Sales Invoice',
            RecordId,
            SalesInvoiceHeader."No.",
            RecordSystemId,
            'SALES_INVOICE',
            FileName,
            Subject,
            RecipientsCsv);

        Success := Client.SendDocumentLinkedEvent(
            Payload,
            EventId,
            CorrelationId,
            'Posted Sales Invoice',
            SalesInvoiceHeader."No.",
            'SALES_INVOICE',
            FileName);

        exit(Success);
    end;

    local procedure ResolveRecipient(var SalesInvoiceHeader: Record "Sales Invoice Header") Recipient: Text[1000]
    var
        Customer: Record Customer;
    begin
        if SalesInvoiceHeader."Sell-to E-Mail" <> '' then
            exit(CopyStr(SalesInvoiceHeader."Sell-to E-Mail", 1, MaxStrLen(Recipient)));

        if Customer.Get(SalesInvoiceHeader."Sell-to Customer No.") then
            if Customer."E-Mail" <> '' then
                exit(CopyStr(Customer."E-Mail", 1, MaxStrLen(Recipient)));

        exit('recipient@example.invalid');
    end;

    local procedure GetSetup(var Setup: Record "GPI Doc Delivery Setup")
    begin
        if not Setup.Get('SETUP') then begin
            Setup.Init();
            Setup."Primary Key" := 'SETUP';
            Setup."Integration Enabled" := false;
            Setup."Log Successful Events" := true;
            Setup.Insert(true);
        end;
    end;

    local procedure MakeStableId(Value: Text[100]) StableId: Text[100]
    begin
        StableId := CopyStr(LowerCase(Value), 1, MaxStrLen(StableId));
        StableId := ConvertStr(StableId, ':./\ {}[]()_', '------------');
    end;
}
