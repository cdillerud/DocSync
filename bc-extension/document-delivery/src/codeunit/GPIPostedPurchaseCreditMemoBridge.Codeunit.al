codeunit 70150008 "GPI Purch Cr Memo Bridge"
{
    Access = Internal;

    procedure SendPostedPurchaseCreditMemoTestEvent(var PurchCrMemoHeader: Record "Purch. Cr. Memo Hdr.") Success: Boolean
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

        if PurchCrMemoHeader."No." = '' then
            Error('A posted purchase credit memo number is required.');

        EventId := MakeStableId('posted-purchase-credit-memo-test-' + PurchCrMemoHeader."No.");
        CorrelationId := MakeStableId('posted-purchase-credit-memo-' + PurchCrMemoHeader."No.");
        RecordId := CopyStr(Format(PurchCrMemoHeader.RecordId(), 0, 9), 1, MaxStrLen(RecordId));
        RecordSystemId := CopyStr(Format(PurchCrMemoHeader.SystemId), 1, MaxStrLen(RecordSystemId));
        FileName := CopyStr(PurchCrMemoHeader."No." + '.pdf', 1, MaxStrLen(FileName));
        Subject := CopyStr('Posted Purchase Credit Memo ' + PurchCrMemoHeader."No.", 1, MaxStrLen(Subject));
        RecipientsCsv := ResolveRecipient(PurchCrMemoHeader);

        Payload := Builder.BuildDeliverySentPayload(
            Setup,
            EventId,
            CorrelationId,
            'Posted Purchase Credit Memo',
            RecordId,
            PurchCrMemoHeader."No.",
            RecordSystemId,
            'PURCHASE_CREDIT_MEMO',
            FileName,
            Subject,
            RecipientsCsv);

        Success := Client.SendDeliverySentEvent(
            Payload,
            EventId,
            CorrelationId,
            'Posted Purchase Credit Memo',
            PurchCrMemoHeader."No.",
            'PURCHASE_CREDIT_MEMO',
            FileName);

        exit(Success);
    end;

    procedure SendPostedPurchaseCreditMemoDocumentLinkEvent(var PurchCrMemoHeader: Record "Purch. Cr. Memo Hdr.") Success: Boolean
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

        if PurchCrMemoHeader."No." = '' then
            Error('A posted purchase credit memo number is required.');

        if Setup."Document Link Template" = '' then
            Error('Document Link Template must be configured before sending a GPI Hub document link event.');

        LinkVersionKey := Setup."Document Link Version";
        if LinkVersionKey = '' then
            LinkVersionKey := 'v1';

        EventId := MakeStableId('posted-purchase-credit-memo-document-link-' + PurchCrMemoHeader."No." + '-' + LinkVersionKey);
        CorrelationId := MakeStableId('posted-purchase-credit-memo-document-link-' + PurchCrMemoHeader."No." + '-' + LinkVersionKey);
        RecordId := CopyStr(Format(PurchCrMemoHeader.RecordId(), 0, 9), 1, MaxStrLen(RecordId));
        RecordSystemId := CopyStr(Format(PurchCrMemoHeader.SystemId), 1, MaxStrLen(RecordSystemId));
        FileName := CopyStr(PurchCrMemoHeader."No." + '.pdf', 1, MaxStrLen(FileName));
        Subject := CopyStr('Posted Purchase Credit Memo Document Link ' + PurchCrMemoHeader."No.", 1, MaxStrLen(Subject));
        RecipientsCsv := ResolveRecipient(PurchCrMemoHeader);

        Payload := Builder.BuildDeliverySentPayload(
            Setup,
            EventId,
            CorrelationId,
            'Posted Purchase Credit Memo',
            RecordId,
            PurchCrMemoHeader."No.",
            RecordSystemId,
            'PURCHASE_CREDIT_MEMO',
            FileName,
            Subject,
            RecipientsCsv);

        Success := Client.SendDocumentLinkedEvent(
            Payload,
            EventId,
            CorrelationId,
            'Posted Purchase Credit Memo',
            PurchCrMemoHeader."No.",
            'PURCHASE_CREDIT_MEMO',
            FileName);

        exit(Success);
    end;

    local procedure ResolveRecipient(var PurchCrMemoHeader: Record "Purch. Cr. Memo Hdr.") Recipient: Text[1000]
    var
        Vendor: Record Vendor;
    begin
        if PurchCrMemoHeader."Buy-from Vendor No." <> '' then
            if Vendor.Get(PurchCrMemoHeader."Buy-from Vendor No.") then
                if Vendor."E-Mail" <> '' then
                    exit(CopyStr(Vendor."E-Mail", 1, MaxStrLen(Recipient)));

        if PurchCrMemoHeader."Pay-to Vendor No." <> '' then
            if Vendor.Get(PurchCrMemoHeader."Pay-to Vendor No.") then
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
            Setup."Document Link Version" := 'v1';
            Setup.Insert(true);
        end;
    end;

    local procedure MakeStableId(Value: Text[100]) StableId: Text[100]
    begin
        StableId := CopyStr(LowerCase(Value), 1, MaxStrLen(StableId));
        StableId := ConvertStr(StableId, ':./\\ {}[]()_', '------------');
    end;
}
