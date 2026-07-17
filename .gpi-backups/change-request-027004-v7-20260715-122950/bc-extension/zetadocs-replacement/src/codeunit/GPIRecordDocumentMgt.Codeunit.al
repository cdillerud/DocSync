codeunit 70620 "GPI Record Document Mgt."
{
    Permissions =
        tabledata "GPI Record Document" = rimd,
        tabledata "GPI Document Delivery Log" = r,
        tabledata "GPI SharePoint Archive Setup" = r;

    procedure UploadDocument(SourceTableId: Integer; SourceSystemId: Guid; SourceDocumentType: Text[50]; SourceDocumentNo: Code[20]; SourcePartyType: Text[20]; SourcePartyNo: Code[20]; CustomerNo: Code[20]; VendorNo: Code[20]; LocationCode: Code[10]; OriginalFileName: Text; ContentType: Text; FileSize: BigInteger; var ContentStream: InStream): Integer
    var
        Document: Record "GPI Record Document";
        Setup: Record "GPI SharePoint Archive Setup";
        Storage: Codeunit "External File Storage";
        FileScenario: Codeunit "File Scenario";
        TempAccount: Record "File Account" temporary;
        ParentPath: Text;
        SharePointPath: Text;
        SharePointFileName: Text[250];
        SharePointUrl: Text[2048];
        SharePointItemId: Text[250];
        ErrorText: Text;
        IsHandled: Boolean;
        OperationSucceeded: Boolean;
    begin
        ValidateUpload(SourceSystemId, OriginalFileName, FileSize);
        GetSetup(Setup);

        Document.Init();
        Document."Source Table ID" := SourceTableId;
        Document."Source SystemId" := SourceSystemId;
        Document."Source Document Type" := SourceDocumentType;
        Document."Source Document No." := SourceDocumentNo;
        Document."Source Party Type" := SourcePartyType;
        Document."Source Party No." := SourcePartyNo;
        Document."Customer No." := CustomerNo;
        Document."Vendor No." := VendorNo;
        Document."Location Code" := LocationCode;
        Document."Original File Name" := CopyStr(OriginalFileName, 1, MaxStrLen(Document."Original File Name"));
        Document."Content Type" := CopyStr(ContentType, 1, MaxStrLen(Document."Content Type"));
        Document."File Size" := FileSize;
        Document.Category := 'General';
        Document."Uploaded By" := CopyStr(UserId(), 1, MaxStrLen(Document."Uploaded By"));
        Document."Uploaded Date/Time" := CurrentDateTime();
        Document.Status := Document.Status::Pending;
        Document.Insert(true);

        OnBeforeUploadRecordDocument(
            Document,
            IsHandled,
            OperationSucceeded,
            SharePointPath,
            SharePointFileName,
            SharePointItemId,
            SharePointUrl,
            ErrorText);

        if IsHandled then begin
            CompleteUpload(Document, OperationSucceeded, SharePointPath, SharePointFileName, SharePointItemId, SharePointUrl, ErrorText);
            exit(Document."Entry No.");
        end;

        if not FileScenario.GetSpecificFileAccount(Enum::"File Scenario"::"GPI Document Archive", TempAccount) then begin
            CompleteUpload(Document, false, '', '', '', '', 'Assign GPI Document Archive to a SharePoint External File Account.');
            Error('%1', Document."Last Error");
        end;

        Storage.Initialize(TempAccount);
        ParentPath := PathMgt.BuildParentPath(Storage, Document, Setup);
        SharePointFileName := PathMgt.GetUniqueFileName(Storage, ParentPath, OriginalFileName, Document."Entry No.");
        SharePointPath := Storage.CombinePath(ParentPath, SharePointFileName);

        ClearLastError();
        if not Storage.CreateFile(SharePointPath, ContentStream) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := 'The document could not be uploaded to SharePoint.';
            CompleteUpload(Document, false, SharePointPath, SharePointFileName, '', '', ErrorText);
            Error('%1', ErrorText);
        end;

        SharePointUrl := CopyStr(PathMgt.BuildWebUrl(Setup, SharePointPath), 1, MaxStrLen(SharePointUrl));
        CompleteUpload(Document, true, SharePointPath, SharePointFileName, '', SharePointUrl, '');
        exit(Document."Entry No.");
    end;

    procedure OpenDocument(EntryNo: Integer)
    var
        Document: Record "GPI Record Document";
    begin
        Document.Get(EntryNo);
        if Document.Status <> Document.Status::Uploaded then
            Error('The document is not available in SharePoint. Status: %1. %2', Document.Status, Document."Last Error");
        if Document."SharePoint URL" = '' then
            Error('No SharePoint URL is stored for %1.', Document."Original File Name");
        Hyperlink(Document."SharePoint URL");
    end;

    procedure BuildDocumentBuffer(SourceTableId: Integer; SourceSystemId: Guid; var TempDocuments: Record "GPI Record Document" temporary)
    var
        Document: Record "GPI Record Document";
    begin
        TempDocuments.Reset();
        TempDocuments.DeleteAll();

        if IsNullGuid(SourceSystemId) then
            exit;

        Document.SetRange("Source Table ID", SourceTableId);
        Document.SetRange("Source SystemId", SourceSystemId);
        Document.SetFilter(Status, '<>%1', Document.Status::Deleted);
        if Document.FindSet() then
            repeat
                TempDocuments := Document;
                TempDocuments.Insert();
            until Document.Next() = 0;

        AddSentDocumentsToBuffer(SourceTableId, SourceSystemId, TempDocuments);
    end;

    procedure AddSentDocumentsToBuffer(SourceTableId: Integer; SourceSystemId: Guid; var TempDocuments: Record "GPI Record Document" temporary)
    var
        DeliveryLog: Record "GPI Document Delivery Log";
        ActivityDateTime: DateTime;
        EntryReference: Integer;
    begin
        if IsNullGuid(SourceSystemId) then
            exit;

        DeliveryLog.SetRange("Source Table ID", SourceTableId);
        DeliveryLog.SetRange("Source SystemId", SourceSystemId);
        DeliveryLog.SetFilter(
            Status,
            '%1|%2',
            DeliveryLog.Status::Sent,
            DeliveryLog.Status::Archived);

        if DeliveryLog.FindSet() then
            repeat
                EntryReference := -DeliveryLog."Entry No.";
                if not TempDocuments.Get(EntryReference) then begin
                    TempDocuments.Init();
                    TempDocuments."Entry No." := EntryReference;
                    TempDocuments."Source Table ID" := SourceTableId;
                    TempDocuments."Source SystemId" := SourceSystemId;
                    TempDocuments."Source Document Type" := DeliveryLog."Source Document Type";
                    TempDocuments."Source Document No." := DeliveryLog."Source Document No.";
                    TempDocuments."Source Party Type" := DeliveryLog."Source Party Type";
                    TempDocuments."Source Party No." := DeliveryLog."Source Party No.";
                    TempDocuments."Customer No." := DeliveryLog."Customer No.";
                    TempDocuments."Location Code" := DeliveryLog."Location Code";
                    TempDocuments."Original File Name" := GetDeliveryFileName(DeliveryLog);
                    TempDocuments.Category := CopyStr(
                        Format(DeliveryLog."Delivery Document Type"),
                        1,
                        MaxStrLen(TempDocuments.Category));
                    TempDocuments.Description := CopyStr(
                        GetDeliveryDisplayStatus(DeliveryLog),
                        1,
                        MaxStrLen(TempDocuments.Description));
                    TempDocuments."Uploaded By" := DeliveryLog."Completed By";

                    ActivityDateTime := DeliveryLog."Completed Date/Time";
                    if ActivityDateTime = 0DT then
                        ActivityDateTime := DeliveryLog."Created Date/Time";
                    TempDocuments."Uploaded Date/Time" := ActivityDateTime;
                    TempDocuments.Status := TempDocuments.Status::Uploaded;
                    TempDocuments.Insert();
                end;
            until DeliveryLog.Next() = 0;
    end;

    procedure OpenDocumentReference(EntryReference: Integer)
    begin
        if EntryReference = 0 then
            Error('The selected document does not have a valid document reference.');

        if EntryReference > 0 then begin
            OpenDocument(EntryReference);
            exit;
        end;

        OpenSentDocument(-EntryReference);
    end;

    procedure OpenSentDocument(DeliveryLogEntryNo: Integer)
    var
        DeliveryLog: Record "GPI Document Delivery Log";
        DocumentInStream: InStream;
        FileName: Text;
    begin
        DeliveryLog.Get(DeliveryLogEntryNo);
        if not (DeliveryLog.Status in [DeliveryLog.Status::Sent, DeliveryLog.Status::Archived]) then
            Error(
                'Delivery log entry %1 is not a successfully sent document. Status: %2.',
                DeliveryLog."Entry No.",
                DeliveryLog.Status);

        if DeliveryLog."SharePoint URL" <> '' then begin
            Hyperlink(DeliveryLog."SharePoint URL");
            exit;
        end;

        DeliveryLog.CalcFields("Document Content");
        if not DeliveryLog."Document Content".HasValue then
            Error(
                'The exact PDF is no longer stored in Business Central and no SharePoint URL is available for %1.',
                GetDeliveryFileName(DeliveryLog));

        FileName := GetDeliveryFileName(DeliveryLog);
        DeliveryLog."Document Content".CreateInStream(DocumentInStream);
        DownloadFromStream(
            DocumentInStream,
            '',
            '',
            'PDF files (*.pdf)|*.pdf',
            FileName);
    end;

    local procedure GetDeliveryFileName(DeliveryLog: Record "GPI Document Delivery Log"): Text[250]
    var
        FileName: Text[250];
    begin
        FileName := DeliveryLog."Attachment Filename";
        if FileName <> '' then
            exit(FileName);

        FileName := CopyStr(
            StrSubstNo(
                '%1 %2.pdf',
                Format(DeliveryLog."Delivery Document Type"),
                DeliveryLog."Source Document No."),
            1,
            MaxStrLen(FileName));
        exit(FileName);
    end;

    local procedure GetDeliveryDisplayStatus(DeliveryLog: Record "GPI Document Delivery Log"): Text
    begin
        case DeliveryLog."Archive Status" of
            DeliveryLog."Archive Status"::Archived:
                exit('Sent / Archived');
            DeliveryLog."Archive Status"::Failed:
                exit('Sent / Archive Failed');
            else
                exit('Sent');
        end;
    end;

    procedure ValidateUpload(SourceSystemId: Guid; OriginalFileName: Text; FileSize: BigInteger)
    var
        Setup: Record "GPI SharePoint Archive Setup";
        MaximumBytes: BigInteger;
        Extension: Text;
        BlockedExtensions: Text;
    begin
        if IsNullGuid(SourceSystemId) then
            Error('Save the Business Central record before attaching documents.');
        if OriginalFileName = '' then
            Error('The uploaded file must have a filename.');

        GetSetup(Setup);
        MaximumBytes := GetMaximumUploadSizeMB(Setup) * 1024 * 1024;
        if (FileSize > 0) and (FileSize > MaximumBytes) then
            Error('The file is %1 bytes. The maximum record document upload size is %2 MB.', FileSize, GetMaximumUploadSizeMB(Setup));

        Extension := LowerCase(GetExtension(OriginalFileName));
        BlockedExtensions := LowerCase(GetBlockedUploadExtensions(Setup));
        if (Extension <> '') and (StrPos(';' + BlockedExtensions + ';', ';' + Extension + ';') > 0) then
            Error('Files with the %1 extension cannot be uploaded.', Extension);
    end;

    procedure GetMaximumUploadSizeMB(): Integer
    var
        Setup: Record "GPI SharePoint Archive Setup";
    begin
        GetSetup(Setup);
        exit(GetMaximumUploadSizeMB(Setup));
    end;

    procedure GetBlockedUploadExtensions(): Text
    var
        Setup: Record "GPI SharePoint Archive Setup";
    begin
        GetSetup(Setup);
        exit(GetBlockedUploadExtensions(Setup));
    end;

    procedure GetSetup(var Setup: Record "GPI SharePoint Archive Setup")
    var
        ArchiveMgt: Codeunit "GPI SharePoint Archive";
    begin
        ArchiveMgt.GetSetup(Setup);
    end;

    local procedure CompleteUpload(var Document: Record "GPI Record Document"; OperationSucceeded: Boolean; SharePointPath: Text; SharePointFileName: Text[250]; SharePointItemId: Text[250]; SharePointUrl: Text[2048]; ErrorText: Text)
    begin
        Document."SharePoint Path" := CopyStr(SharePointPath, 1, MaxStrLen(Document."SharePoint Path"));
        Document."SharePoint File Name" := SharePointFileName;
        Document."SharePoint Item ID" := SharePointItemId;
        Document."SharePoint URL" := CopyStr(SharePointUrl, 1, MaxStrLen(Document."SharePoint URL"));

        if OperationSucceeded then begin
            Document.Status := Document.Status::Uploaded;
            Clear(Document."Last Error");
        end else begin
            Document.Status := Document.Status::Failed;
            if ErrorText = '' then
                ErrorText := 'The document could not be uploaded to SharePoint.';
            Document."Last Error" := CopyStr(ErrorText, 1, MaxStrLen(Document."Last Error"));
        end;

        Document.Modify(true);
    end;

    local procedure GetMaximumUploadSizeMB(Setup: Record "GPI SharePoint Archive Setup"): Integer
    begin
        if Setup."Maximum Upload Size MB" > 0 then
            exit(Setup."Maximum Upload Size MB");
        exit(25);
    end;

    local procedure GetBlockedUploadExtensions(Setup: Record "GPI SharePoint Archive Setup"): Text
    begin
        if Setup."Blocked Upload Extensions" <> '' then
            exit(NormalizeExtensions(Setup."Blocked Upload Extensions"));
        exit('.exe;.com;.bat;.cmd;.msi;.dll;.scr;.js;.vbs;.ps1');
    end;

    local procedure NormalizeExtensions(Value: Text): Text
    begin
        Value := DelChr(Value, '=', ' ');
        Value := ConvertStr(Value, ',', ';');
        exit(Value);
    end;

    local procedure GetExtension(FileName: Text): Text
    var
        CharacterNo: Integer;
    begin
        for CharacterNo := StrLen(FileName) downto 1 do
            if CopyStr(FileName, CharacterNo, 1) = '.' then
                exit(CopyStr(FileName, CharacterNo));
        exit('');
    end;

    [IntegrationEvent(false, false)]
    procedure OnBeforeUploadRecordDocument(var Document: Record "GPI Record Document"; var IsHandled: Boolean; var OperationSucceeded: Boolean; var SharePointPath: Text; var SharePointFileName: Text[250]; var SharePointItemId: Text[250]; var SharePointUrl: Text[2048]; var ErrorText: Text)
    begin
    end;

    var
        PathMgt: Codeunit "GPI Record Document Path Mgt.";
}