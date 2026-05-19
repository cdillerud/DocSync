codeunit 70150002 "GPI Hub Event Builder"
{
    Access = Internal;

    procedure BuildSampleDeliverySentPayload(var Setup: Record "GPI Doc Delivery Setup"; EventId: Text[100]; CorrelationId: Text[100]) Payload: Text
    var
        Root: JsonObject;
        BCRecord: JsonObject;
        Recipients: JsonObject;
        ToArray: JsonArray;
        CcArray: JsonArray;
        BccArray: JsonArray;
        Metadata: JsonObject;
    begin
        Root.Add('event_id', EventId);
        Root.Add('idempotency_key', EventId);
        Root.Add('correlation_id', CorrelationId);
        Root.Add('event_timestamp', Format(CurrentDateTime(), 0, 9));
        Root.Add('source_app', 'BC_AL_EXTENSION_SANDBOX');
        Root.Add('source_system', 'BC_NATIVE');
        Root.Add('actor', UserId());

        BCRecord.Add('company_id', Setup."Company ID");
        BCRecord.Add('company_name', Setup."Company Name");
        BCRecord.Add('environment', Setup."Environment Name");
        BCRecord.Add('record_type', 'Posted Sales Invoice');
        BCRecord.Add('record_id', 'al-sandbox-record-guid');
        BCRecord.Add('record_no', 'AL-SAMPLE-INV-001');
        BCRecord.Add('record_system_id', 'al-sandbox-system-id');
        BCRecord.Add('posted', true);
        Root.Add('bc_record', BCRecord);

        Root.Add('document_no', 'AL-SAMPLE-INV-001');
        Root.Add('document_type', 'SALES_INVOICE');
        Root.Add('file_name', 'AL-SAMPLE-INV-001.pdf');
        Root.Add('delivery_method', 'bc_email');
        Root.Add('delivery_status', 'sent');
        Root.Add('template_code', 'SALES_INVOICE_DEFAULT');
        Root.Add('subject', 'Sandbox Invoice AL-SAMPLE-INV-001');
        Root.Add('email_message_id', 'al-sandbox-message-id-001');
        Root.Add('recipient_resolution_method', 'manual_test');

        ToArray.Add('recipient@example.invalid');
        Recipients.Add('to', ToArray);
        Recipients.Add('cc', CcArray);
        Recipients.Add('bcc', BccArray);
        Root.Add('recipients', Recipients);

        Metadata.Add('test_payload', true);
        Metadata.Add('notes', 'Business Central AL sandbox sample delivery event');
        Root.Add('metadata', Metadata);

        Root.WriteTo(Payload);
    end;

    procedure BuildDeliverySentPayload(
        var Setup: Record "GPI Doc Delivery Setup";
        EventId: Text[100];
        CorrelationId: Text[100];
        RecordType: Text[100];
        RecordId: Text[100];
        RecordNo: Code[50];
        RecordSystemId: Text[100];
        DocumentType: Text[50];
        FileName: Text[250];
        Subject: Text[250];
        RecipientsCsv: Text[1000]) Payload: Text
    var
        Root: JsonObject;
        BCRecord: JsonObject;
        Recipients: JsonObject;
        ToArray: JsonArray;
        CcArray: JsonArray;
        BccArray: JsonArray;
        Metadata: JsonObject;
    begin
        Root.Add('event_id', EventId);
        Root.Add('idempotency_key', EventId);
        Root.Add('correlation_id', CorrelationId);
        Root.Add('event_timestamp', Format(CurrentDateTime(), 0, 9));
        Root.Add('source_app', 'BC_AL_EXTENSION');
        Root.Add('source_system', 'BC_NATIVE');
        Root.Add('actor', UserId());

        BCRecord.Add('company_id', Setup."Company ID");
        BCRecord.Add('company_name', Setup."Company Name");
        BCRecord.Add('environment', Setup."Environment Name");
        BCRecord.Add('record_type', RecordType);
        BCRecord.Add('record_id', RecordId);
        BCRecord.Add('record_no', RecordNo);
        BCRecord.Add('record_system_id', RecordSystemId);
        BCRecord.Add('posted', true);
        Root.Add('bc_record', BCRecord);

        Root.Add('document_no', RecordNo);
        Root.Add('document_type', DocumentType);
        Root.Add('file_name', FileName);
        Root.Add('delivery_method', 'bc_email');
        Root.Add('delivery_status', 'sent');
        Root.Add('template_code', 'BC_NATIVE');
        Root.Add('subject', Subject);
        Root.Add('recipient_resolution_method', 'bc_native');

        AddCsvRecipients(ToArray, RecipientsCsv);
        Recipients.Add('to', ToArray);
        Recipients.Add('cc', CcArray);
        Recipients.Add('bcc', BccArray);
        Root.Add('recipients', Recipients);

        Metadata.Add('test_payload', false);
        Metadata.Add('notes', 'Business Central native delivery event');
        Root.Add('metadata', Metadata);

        Root.WriteTo(Payload);
    end;

    local procedure AddCsvRecipients(var TargetArray: JsonArray; RecipientsCsv: Text)
    var
        Remaining: Text;
        Recipient: Text;
        CommaPosition: Integer;
    begin
        Remaining := RecipientsCsv;

        while Remaining <> '' do begin
            CommaPosition := StrPos(Remaining, ',');
            if CommaPosition = 0 then begin
                Recipient := DelChr(Remaining, '<>', ' ');
                Remaining := '';
            end else begin
                Recipient := DelChr(CopyStr(Remaining, 1, CommaPosition - 1), '<>', ' ');
                Remaining := CopyStr(Remaining, CommaPosition + 1);
            end;

            if Recipient <> '' then
                TargetArray.Add(Recipient);
        end;
    end;
}
