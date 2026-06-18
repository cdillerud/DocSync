codeunit 70520 "GPI Document Link Mgt."
{
    Permissions = tabledata "GPI Linked Document" = rimd;

    [TryFunction]
    procedure TryStoreFile(SourceTableId: Integer; SourceSystemId: Guid; SourceDocumentType: Text; SourceDocumentNo: Code[50]; SourcePartyNo: Code[20]; SourcePartyName: Text; BusinessArea: Text; FileName: Text; ContentType: Text; FileData: Text; FileSize: Integer; var LinkedDocument: Record "GPI Linked Document")
    begin
        if IsNullGuid(SourceSystemId) then
            Error('Save the Business Central record before adding documents.');
        if FileName = '' then
            Error('The selected file does not have a filename.');
        if FileSize <= 0 then
            Error('The selected file is empty.');
        if FileSize > (8 * 1024 * 1024) then
            Error('%1 is larger than the 8 MB limit.', FileName);
        if FileData = '' then
            Error('The selected file did not contain any data.');
    end;

    procedure CountDocuments(SourceTableId: Integer; SourceSystemId: Guid): Integer
    var
        LinkedDocument: Record "GPI Linked Document";
    begin
        if IsNullGuid(SourceSystemId) then
            exit(0);

        LinkedDocument.SetRange("Source Table ID", SourceTableId);
        LinkedDocument.SetRange("Source System ID", SourceSystemId);
        exit(LinkedDocument.Count());
    end;

    procedure OpenDocuments(SourceTableId: Integer; SourceSystemId: Guid)
    var
        LinkedDocument: Record "GPI Linked Document";
    begin
        LinkedDocument.SetRange("Source Table ID", SourceTableId);
        LinkedDocument.SetRange("Source System ID", SourceSystemId);
        Page.Run(Page::"GPI Linked Documents", LinkedDocument);
    end;
}
