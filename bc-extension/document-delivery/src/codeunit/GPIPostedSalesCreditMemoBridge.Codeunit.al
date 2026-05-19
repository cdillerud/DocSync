codeunit 70150007 "GPI Sales Cr Memo Bridge"
{
    Access = Internal;

    procedure SendPostedSalesCreditMemoTestEvent(var SalesCrMemoHeader: Record "Sales Cr.Memo Header") Success: Boolean
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

        if SalesCrMemoHeader."No." = '' then
            Error('A posted sales credit memo number is required.');

        EventId := MakeStableId('posted-sales-credit-memo-test-' + SalesCrMemoHeader."No.");
        CorrelationId := MakeStableId('posted-sales-credit-memo-' + SalesCrMemoHeader."No.");
        RecordId := CopyStr(Format(SalesCrMemoHeader.RecordId(), 0, 9), 1, MaxStrLen(RecordId));
        RecordSystemId := CopyStr(Format(SalesCrMemoHeader.SystemId), 1, MaxStrLen(RecordSystemId));
        FileName := CopyStr(SalesCrMemoHeader."No." + '.pdf', 1, MaxStrLen(FileName));
        Subject := CopyStr('Posted Sales Credit Memo ' + SalesCrMemoHeader."No.", 1, MaxStrLen(Subject));
        RecipientsCsv := ResolveRecipient(SalesCrMemoHeader);

        Payload := Builder.BuildDeliverySentPayload(
            Setup,
            EventId,
            CorrelationId,
            'Posted Sales Credit Memo',
            RecordId,
            SalesCrMemoHeader."No.",
            RecordSystemId,
            'SALES_CREDIT_MEMO',
            FileName,
            Subject,
            RecipientsCsv);

        Success := Client.SendDeliverySentEvent(
            Payload,
            EventId,
            CorrelationId,
            'Posted Sales Credit Memo',
            SalesCrMemoHeader."No.",
            'SALES_CREDIT_MEMO',
            FileName);

        exit(Success);
    end;

    procedure SendPostedSalesCreditMemoDocumentLinkEvent(var SalesCrMemoHeader: Record "Sales Cr.Memo Header") Success: Boolean
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

        if SalesCrMemoHeader."No." = '' then
            Error('A posted sales credit memo number is required.');

        if Setup."Document Link Template" = '' then
            Error('Document Link Template must be configured before sending a GPI Hub document link event.');

        LinkVersionKey := Setup."Document Link Version";
        if LinkVersionKey = '' then
            LinkVersionKey := 'v1';

        EventId := MakeStableId('posted-sales-credit-memo-document-link-' + SalesCrMemoHeader."No." + '-' + LinkVersionKey);
        CorrelationId := MakeStableId('posted-sales-credit-memo-document-link-' + SalesCrMemoHeader."No." + '-' + LinkVersionKey);
        RecordId := CopyStr(Format(SalesCrMemoHeader.RecordId(), 0, 9), 1, MaxStrLen(RecordId));
        RecordSystemId := CopyStr(Format(SalesCrMemoHeader.SystemId), 1, MaxStrLen(RecordSystemId));
        FileName := CopyStr(SalesCrMemoHeader."No." + '.pdf', 1, MaxStrLen(FileName));
        Subject := CopyStr('Posted Sales Credit Memo Document Link ' + SalesCrMemoHeader."No.", 1, MaxStrLen(Subject));
        RecipientsCsv := ResolveRecipient(SalesCrMemoHeader);

        Payload := Builder.BuildDeliverySentPayload(
            Setup,
            EventId,
            CorrelationId,
            'Posted Sales Credit Memo',
            RecordId,
            SalesCrMemoHeader."No.",
            RecordSystemId,
            'SALES_CREDIT_MEMO',
            FileName,
            Subject,
            RecipientsCsv);

        Success := Client.SendDocumentLinkedEvent(
            Payload,
            EventId,
            CorrelationId,
            'Posted Sales Credit Memo',
            SalesCrMemoHeader."No.",
            'SALES_CREDIT_MEMO',
            FileName);

        exit(Success);
    end;

    local procedure ResolveRecipient(var SalesCrMemoHeader: Record "Sales Cr.Memo Header") Recipient: Text[1000]
    var
        Customer: Record Customer;
    begin
        if SalesCrMemoHeader."Sell-to E-Mail" <> '' then
            exit(CopyStr(SalesCrMemoHeader."Sell-to E-Mail", 1, MaxStrLen(Recipient)));

        if Customer.Get(SalesCrMemoHeader."Sell-to Customer No.") then
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
            Setup."Document Link Version" := 'v1';
            Setup.Insert(true);
        end;
    end;

    local procedure MakeStableId(Value: Text[100]) StableId: Text[100]
    begin
        StableId := CopyStr(LowerCase(Value), 1, MaxStrLen(StableId));
        StableId := StableId.Replace(':', '-');
        StableId := StableId.Replace('.', '-');
        StableId := StableId.Replace('/', '-');
        StableId := StableId.Replace('\\', '-');
        StableId := StableId.Replace(' ', '-');
        StableId := StableId.Replace('{', '-');
        StableId := StableId.Replace('}', '-');
        StableId := StableId.Replace('[', '-');
        StableId := StableId.Replace(']', '-');
        StableId := StableId.Replace('(', '-');
        StableId := StableId.Replace(')', '-');
        StableId := StableId.Replace('_', '-');
    end;
}
