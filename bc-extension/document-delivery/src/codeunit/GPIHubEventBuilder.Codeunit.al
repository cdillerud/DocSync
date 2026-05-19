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

        AddExternalDocumentLink(Root, Setup, 'Posted Sales Invoice', 'AL-SAMPLE-INV-001', 'AL-SAMPLE-INV-001.pdf');

        Metadata.Add('test_payload', true);
        Metadata.Add('notes', 'Business Central AL sandbox sample delivery event');
        Metadata.Add('document_storage_provider', Setup."Document Storage Provider");
        Metadata.Add('document_link_strategy', 'external_link');
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

        AddExternalDocumentLink(Root, Setup, RecordType, RecordNo, FileName);

        Metadata.Add('test_payload', false);
        Metadata.Add('notes', 'Business Central native delivery event');
        Metadata.Add('document_storage_provider', Setup."Document Storage Provider");
        Metadata.Add('document_link_strategy', 'external_link');
        Root.Add('metadata', Metadata);

        Root.WriteTo(Payload);
    end;

    local procedure AddExternalDocumentLink(var Root: JsonObject; var Setup: Record "GPI Doc Delivery Setup"; RecordType: Text; DocumentNo: Text; FileName: Text)
    var
        SharePoint: JsonObject;
        WebUrl: Text;
        FolderPath: Text;
    begin
        WebUrl := ApplyTemplate(Setup."Document Link Template", Setup, RecordType, DocumentNo, FileName);
        FolderPath := ApplyTemplate(Setup."Document Folder Template", Setup, RecordType, DocumentNo, FileName);

        if (WebUrl = '') and (FolderPath = '') then
            exit;

        SharePoint.Add('site_id', '');
        SharePoint.Add('drive_id', '');
        SharePoint.Add('item_id', '');
        SharePoint.Add('web_url', WebUrl);
        SharePoint.Add('folder_path', FolderPath);
        SharePoint.Add('file_name', FileName);
        SharePoint.Add('storage_status', 'external_link');
        Root.Add('sharepoint', SharePoint);
    end;

    local procedure ApplyTemplate(TemplateText: Text; var Setup: Record "GPI Doc Delivery Setup"; RecordType: Text; DocumentNo: Text; FileName: Text) Result: Text
    var
        RecordTypeUrl: Text;
    begin
        Result := TemplateText;
        if Result = '' then
            exit('');

        RecordTypeUrl := UrlEncodePathSegment(RecordType);

        Result := Result.Replace('{DocumentNo}', DocumentNo);
        Result := Result.Replace('{RecordNo}', DocumentNo);
        Result := Result.Replace('{FileName}', FileName);
        Result := Result.Replace('{RecordType}', RecordType);
        Result := Result.Replace('{RecordTypeUrl}', RecordTypeUrl);
        Result := Result.Replace('{CompanyName}', Setup."Company Name");
        Result := Result.Replace('{EnvironmentName}', Setup."Environment Name");
    end;

    local procedure UrlEncodePathSegment(Value: Text) Result: Text
    begin
        Result := Value;
        Result := Result.Replace(' ', '%20');
        Result := Result.Replace('&', '%26');
        Result := Result.Replace('#', '%23');
        Result := Result.Replace('?', '%3F');
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
