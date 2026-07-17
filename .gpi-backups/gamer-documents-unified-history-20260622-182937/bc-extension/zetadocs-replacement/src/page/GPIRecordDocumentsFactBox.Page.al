page 70620 "GPI Record Documents FactBox"
{
    Caption = 'Documents';
    PageType = CardPart;
    ApplicationArea = All;

    layout
    {
        area(Content)
        {
            usercontrol(DocumentDropZone; "GPI Record Document Dropzone")
            {
                ApplicationArea = All;

                trigger ControlReady()
                begin
                    ControlIsReady := true;
                    InitializeControl();
                    RefreshDocuments();
                end;

                trigger UploadStarted(UploadId: Text; FileName: Text; MimeType: Text; FileSize: Decimal; TotalChunks: Integer)
                var
                    FileSizeAsBigInteger: BigInteger;
                begin
                    FileSizeAsBigInteger := Round(FileSize, 1, '=');
                    DocumentMgt.ValidateUpload(SourceSystemId, FileName, FileSizeAsBigInteger);

                    CurrentUploadId := UploadId;
                    CurrentFileName := CopyStr(FileName, 1, MaxStrLen(CurrentFileName));
                    CurrentMimeType := CopyStr(MimeType, 1, MaxStrLen(CurrentMimeType));
                    CurrentFileSize := FileSizeAsBigInteger;
                    ExpectedChunkCount := TotalChunks;
                    NextChunkNo := 0;
                    Clear(UploadBase64);
                end;

                trigger UploadChunk(UploadId: Text; ChunkNo: Integer; ChunkData: Text)
                begin
                    if UploadId <> CurrentUploadId then
                        Error('The upload session is no longer valid.');
                    if ChunkNo <> NextChunkNo then
                        Error('Upload chunk %1 was received out of sequence. Expected %2.', ChunkNo, NextChunkNo);

                    UploadBase64 += ChunkData;
                    NextChunkNo += 1;
                end;

                trigger UploadCompleted(UploadId: Text)
                var
                    TempBlob: Codeunit "Temp Blob";
                    Base64Convert: Codeunit "Base64 Convert";
                    BlobOutStream: OutStream;
                    BlobInStream: InStream;
                    EntryNo: Integer;
                    UploadedFileName: Text[250];
                begin
                    if UploadId <> CurrentUploadId then
                        Error('The upload session is no longer valid.');
                    if NextChunkNo <> ExpectedChunkCount then
                        Error('The upload is incomplete. Received %1 of %2 chunks.', NextChunkNo, ExpectedChunkCount);

                    TempBlob.CreateOutStream(BlobOutStream);
                    Base64Convert.FromBase64(UploadBase64, BlobOutStream);
                    TempBlob.CreateInStream(BlobInStream);
                    UploadedFileName := CurrentFileName;

                    EntryNo := DocumentMgt.UploadDocument(
                        SourceTableId,
                        SourceSystemId,
                        SourceDocumentType,
                        SourceDocumentNo,
                        SourcePartyType,
                        SourcePartyNo,
                        CustomerNo,
                        VendorNo,
                        LocationCode,
                        CurrentFileName,
                        CurrentMimeType,
                        CurrentFileSize,
                        BlobInStream);

                    ClearUploadState();
                    CurrPage.DocumentDropZone.SetRecordUploadStatus(
                        StrSubstNo('%1 was uploaded.', UploadedFileName),
                        false);
                    RefreshDocuments();

                    if EntryNo = 0 then
                        Error('The document upload did not create a record.');
                end;

                trigger DocumentOpenRequested(EntryNo: Integer)
                begin
                    DocumentMgt.OpenDocument(EntryNo);
                end;

                trigger RefreshRequested()
                begin
                    RefreshDocuments();
                end;
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(UploadDocument)
            {
                ApplicationArea = All;
                Caption = 'Upload Document';
                Image = Import;
                ToolTip = 'Selects a file and uploads it to the SharePoint folder for this Business Central record.';

                trigger OnAction()
                var
                    TempBlob: Codeunit "Temp Blob";
                    FileInStream: InStream;
                    BlobOutStream: OutStream;
                    BlobInStream: InStream;
                    FileName: Text;
                    FileSize: BigInteger;
                begin
                    EnsureContextAvailable();
                    if not UploadIntoStream(
                        'Select a document',
                        '',
                        'All Files (*.*)|*.*',
                        FileName,
                        FileInStream)
                    then
                        exit;

                    TempBlob.CreateOutStream(BlobOutStream);
                    CopyStream(BlobOutStream, FileInStream);
                    FileSize := TempBlob.Length();
                    DocumentMgt.ValidateUpload(SourceSystemId, FileName, FileSize);
                    TempBlob.CreateInStream(BlobInStream);

                    DocumentMgt.UploadDocument(
                        SourceTableId,
                        SourceSystemId,
                        SourceDocumentType,
                        SourceDocumentNo,
                        SourcePartyType,
                        SourcePartyNo,
                        CustomerNo,
                        VendorNo,
                        LocationCode,
                        FileName,
                        '',
                        FileSize,
                        BlobInStream);

                    RefreshDocuments();
                end;
            }

            action(OpenAllDocuments)
            {
                ApplicationArea = All;
                Caption = 'Open Document List';
                Image = View;
                ToolTip = 'Opens the complete SharePoint document list for this Business Central record.';

                trigger OnAction()
                var
                    Document: Record "GPI Record Document";
                begin
                    EnsureContextAvailable();
                    Document.SetRange("Source Table ID", SourceTableId);
                    Document.SetRange("Source SystemId", SourceSystemId);
                    Page.Run(Page::"GPI Record Document List", Document);
                end;
            }
        }
    }

    procedure SetSourceContext(NewSourceTableId: Integer; NewSourceSystemId: Guid; NewSourceDocumentType: Text; NewSourceDocumentNo: Code[20]; NewSourcePartyType: Text; NewSourcePartyNo: Code[20]; NewCustomerNo: Code[20]; NewVendorNo: Code[20]; NewLocationCode: Code[10])
    begin
        SourceTableId := NewSourceTableId;
        SourceSystemId := NewSourceSystemId;
        SourceDocumentType := CopyStr(NewSourceDocumentType, 1, MaxStrLen(SourceDocumentType));
        SourceDocumentNo := NewSourceDocumentNo;
        SourcePartyType := CopyStr(NewSourcePartyType, 1, MaxStrLen(SourcePartyType));
        SourcePartyNo := NewSourcePartyNo;
        CustomerNo := NewCustomerNo;
        VendorNo := NewVendorNo;
        LocationCode := NewLocationCode;

        if ControlIsReady then begin
            InitializeControl();
            RefreshDocuments();
        end;
    end;

    local procedure InitializeControl()
    begin
        CurrPage.DocumentDropZone.InitializeRecordDocuments(
            'Documents',
            DocumentMgt.GetMaximumUploadSizeMB());
        CurrPage.DocumentDropZone.SetRecordContext(not IsNullGuid(SourceSystemId));
    end;

    local procedure RefreshDocuments()
    var
        Document: Record "GPI Record Document";
        DocumentsArray: JsonArray;
        DocumentObject: JsonObject;
        DocumentsJson: Text;
    begin
        if not ControlIsReady then
            exit;

        Clear(DocumentsArray);
        if not IsNullGuid(SourceSystemId) then begin
            Document.SetRange("Source Table ID", SourceTableId);
            Document.SetRange("Source SystemId", SourceSystemId);
            Document.SetFilter(Status, '<>%1', Document.Status::Deleted);
            Document.SetCurrentKey("Source Table ID", "Source SystemId", "Uploaded Date/Time");
            Document.Ascending(false);

            if Document.FindSet() then
                repeat
                    Clear(DocumentObject);
                    DocumentObject.Add('entryNo', Document."Entry No.");
                    DocumentObject.Add('fileName', Document."Original File Name");
                    DocumentObject.Add('category', Document.Category);
                    DocumentObject.Add(
                        'uploadedAt',
                        Format(
                            Document."Uploaded Date/Time",
                            0,
                            '<Month,2>/<Day,2>/<Year4> <Hours24,2>:<Minutes,2>'));
                    DocumentObject.Add('size', Format(Document."File Size"));
                    DocumentObject.Add('status', Format(Document.Status));
                    DocumentsArray.Add(DocumentObject);
                until Document.Next() = 0;
        end;

        DocumentsArray.WriteTo(DocumentsJson);
        CurrPage.DocumentDropZone.SetRecordDocuments(DocumentsJson);
    end;

    local procedure EnsureContextAvailable()
    begin
        if IsNullGuid(SourceSystemId) then
            Error('Save the Business Central record before attaching documents.');
    end;

    local procedure ClearUploadState()
    begin
        Clear(CurrentUploadId);
        Clear(CurrentFileName);
        Clear(CurrentMimeType);
        Clear(CurrentFileSize);
        Clear(ExpectedChunkCount);
        Clear(NextChunkNo);
        Clear(UploadBase64);
    end;

    var
        DocumentMgt: Codeunit "GPI Record Document Mgt.";
        SourceTableId: Integer;
        SourceSystemId: Guid;
        SourceDocumentType: Text[50];
        SourceDocumentNo: Code[20];
        SourcePartyType: Text[20];
        SourcePartyNo: Code[20];
        CustomerNo: Code[20];
        VendorNo: Code[20];
        LocationCode: Code[10];
        ControlIsReady: Boolean;
        CurrentUploadId: Text;
        CurrentFileName: Text[250];
        CurrentMimeType: Text[100];
        CurrentFileSize: BigInteger;
        ExpectedChunkCount: Integer;
        NextChunkNo: Integer;
        UploadBase64: Text;
}
