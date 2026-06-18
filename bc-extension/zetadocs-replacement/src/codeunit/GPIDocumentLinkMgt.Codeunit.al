codeunit 70520 "GPI Document Link Mgt."
{
    Permissions = tabledata "GPI Linked Document" = rimd;

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
