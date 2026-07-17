controladdin "GPI Record Document Dropzone"
{
    RequestedHeight = 330;
    MinimumHeight = 220;
    MaximumHeight = 600;
    RequestedWidth = 320;
    MinimumWidth = 240;
    HorizontalStretch = true;
    VerticalStretch = true;
    Scripts = 'src/controladdin/recorddocuments/recordDocuments.js';
    StartupScript = 'src/controladdin/recorddocuments/startup.js';
    StyleSheets = 'src/controladdin/recorddocuments/recordDocuments.css';

    procedure InitializeRecordDocuments(CaptionText: Text; MaxFileSizeMB: Integer);
    procedure SetRecordContext(ContextAvailable: Boolean);
    procedure SetRecordDocuments(DocumentsJson: Text);
    procedure SetRecordUploadStatus(StatusText: Text; IsError: Boolean);

    event ControlReady();
    event UploadStarted(UploadId: Text; FileName: Text; MimeType: Text; FileSize: Decimal; TotalChunks: Integer);
    event UploadChunk(UploadId: Text; ChunkNo: Integer; ChunkData: Text);
    event UploadCompleted(UploadId: Text);
    event DocumentOpenRequested(EntryNo: Integer);
    event DocumentDeleteRequested(EntryNo: Integer);
    event RefreshRequested();
}
