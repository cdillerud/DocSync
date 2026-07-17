codeunit 70620 "GPI Record Document Mgt."
{
    Permissions =
        tabledata "GPI Record Document" = rimd,
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
