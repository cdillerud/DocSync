codeunit 70150006 "GPI Posted Purch Inv Bridge"
{
    Access = Internal;

    procedure SendPostedPurchaseInvoiceTestEvent(var PurchInvHeader: Record "Purch. Inv. Header") Success: Boolean
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

        if PurchInvHeader."No." = '' then
            Error('A posted purchase invoice number is required.');

        EventId := MakeStableId('posted-purchase-invoice-test-' + PurchInvHeader."No.");
        CorrelationId := MakeStableId('posted-purchase-invoice-' + PurchInvHeader."No.");
        RecordId := CopyStr(Format(PurchInvHeader.RecordId(), 0, 9), 1, MaxStrLen(RecordId));
        RecordSystemId := CopyStr(Format(PurchInvHeader.SystemId), 1, MaxStrLen(RecordSystemId));
        FileName := CopyStr(PurchInvHeader."No." + '.pdf', 1, MaxStrLen(FileName));
        Subject := CopyStr('Posted Purchase Invoice ' + PurchInvHeader."No.", 1, MaxStrLen(Subject));
        RecipientsCsv := ResolveRecipient(PurchInvHeader);

        Payload := Builder.BuildDeliverySentPayload(
            Setup,
            EventId,
            CorrelationId,
            'Posted Purchase Invoice',
            RecordId,
            PurchInvHeader."No.",
            RecordSystemId,
            'PURCHASE_INVOICE',
            FileName,
            Subject,
            RecipientsCsv);

        Success := Client.SendDeliverySentEvent(
            Payload,
            EventId,
            CorrelationId,
            'Posted Purchase Invoice',
            PurchInvHeader."No.",
            'PURCHASE_INVOICE',
            FileName);

        exit(Success);
    end;

    procedure SendPostedPurchaseInvoiceDocumentLinkEvent(var PurchInvHeader: Record "Purch. Inv. Header") Success: Boolean
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
        LinkVersionKey: Text[100];
    begin
        GetSetup(Setup);

        if PurchInvHeader."No." = '' then
            Error('A posted purchase invoice number is required.');

        if Setup."Document Link Template" = '' then
            Error('Document Link Template must be configured before sending a GPI Hub document link event.');

        LinkVersionKey := MakeStableId(Setup."Document Folder Template" + '-' + Setup."Document Link Template");
        EventId := MakeStableId('posted-purchase-invoice-document-link-' + PurchInvHeader."No." + '-' + LinkVersionKey);
        CorrelationId := MakeStableId('posted-purchase-invoice-document-link-' + PurchInvHeader."No." + '-' + LinkVersionKey);
        RecordId := CopyStr(Format(PurchInvHeader.RecordId(), 0, 9), 1, MaxStrLen(RecordId));
        RecordSystemId := CopyStr(Format(PurchInvHeader.SystemId), 1, MaxStrLen(RecordSystemId));
        FileName := CopyStr(PurchInvHeader."No." + '.pdf', 1, MaxStrLen(FileName));
        Subject := CopyStr('Posted Purchase Invoice Document Link ' + PurchInvHeader."No.", 1, MaxStrLen(Subject));
        RecipientsCsv := ResolveRecipient(PurchInvHeader);

        Payload := Builder.BuildDeliverySentPayload(
            Setup,
            EventId,
            CorrelationId,
            'Posted Purchase Invoice',
            RecordId,
            PurchInvHeader."No.",
            RecordSystemId,
            'PURCHASE_INVOICE',
            FileName,
            Subject,
            RecipientsCsv);

        Success := Client.SendDocumentLinkedEvent(
            Payload,
            EventId,
            CorrelationId,
            'Posted Purchase Invoice',
            PurchInvHeader."No.",
            'PURCHASE_INVOICE',
            FileName);

        exit(Success);
    end;

    local procedure ResolveRecipient(var PurchInvHeader: Record "Purch. Inv. Header") Recipient: Text[1000]
    var
        Vendor: Record Vendor;
    begin
        if PurchInvHeader."Buy-from Vendor No." <> '' then
            if Vendor.Get(PurchInvHeader."Buy-from Vendor No.") then
                if Vendor."E-Mail" <> '' then
                    exit(CopyStr(Vendor."E-Mail", 1, MaxStrLen(Recipient)));

        if PurchInvHeader."Pay-to Vendor No." <> '' then
            if Vendor.Get(PurchInvHeader."Pay-to Vendor No.") then
                if Vendor."E-Mail" <> '' then
                    exit(CopyStr(Vendor."E-Mail", 1, MaxStrLen(Recipient)));

        exit('vendor@example.invalid');
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
