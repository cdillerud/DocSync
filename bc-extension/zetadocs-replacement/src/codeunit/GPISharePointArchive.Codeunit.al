codeunit 70516 "GPI SharePoint Archive"
{
    Permissions =
        tabledata "GPI Document Delivery Log" = rm,
        tabledata "GPI SharePoint Archive Setup" = rimd;

    procedure ArchiveDeliveryLog(var LogEntry: Record "GPI Document Delivery Log")
    var
        Setup: Record "GPI SharePoint Archive Setup";
        ArchivePath: Text;
        ArchiveFileName: Text[250];
        ErrorText: Text;
    begin
        GetSetup(Setup);
        if not Setup.Enabled then
            exit;
        if LogEntry.Status <> LogEntry.Status::Sent then
            exit;
        if LogEntry."Archive Status" = LogEntry."Archive Status"::Archived then
            exit;

        LogEntry."Archive Attempt Count" += 1;
        LogEntry."Last Archive Attempt" := CurrentDateTime;
        LogEntry."Archive Status" := LogEntry."Archive Status"::Pending;
        Clear(LogEntry."Last Archive Error");
        LogEntry.Modify(false);

        ClearLastError();
        if not TryArchive(LogEntry, Setup, ArchivePath, ArchiveFileName) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := 'The document could not be archived to SharePoint.';
            LogEntry."Archive Status" := LogEntry."Archive Status"::Failed;
            LogEntry."Last Archive Error" := CopyStr(ErrorText, 1, MaxStrLen(LogEntry."Last Archive Error"));
            LogEntry.Modify(false);
            exit;
        end;

        LogEntry."Archive Status" := LogEntry."Archive Status"::Archived;
        LogEntry."Archived Date/Time" := CurrentDateTime;
        LogEntry."Archive Path" := CopyStr(ArchivePath, 1, MaxStrLen(LogEntry."Archive Path"));
        LogEntry."Archive File Name" := ArchiveFileName;
        LogEntry."SharePoint URL" := CopyStr(PathMgt.BuildWebUrl(Setup, ArchivePath), 1, MaxStrLen(LogEntry."SharePoint URL"));
        Clear(LogEntry."Last Archive Error");

        if Setup."Clear Local PDF After Archive" then begin
            Clear(LogEntry."Document Content");
            LogEntry."Local PDF Cleared" := true;
        end;
        LogEntry.Modify(false);
    end;

    procedure TestConnection()
    var
        Setup: Record "GPI SharePoint Archive Setup";
        AccountName: Text;
        ErrorText: Text;
    begin
        GetSetup(Setup);
        Setup."Last Connection Test" := CurrentDateTime;
        ClearLastError();
        if TryConnection(Setup, AccountName) then begin
            Setup."Last Connection Result" := CopyStr(StrSubstNo('Success. %1 can access the configured SharePoint archive.', AccountName), 1, MaxStrLen(Setup."Last Connection Result"));
            Setup.Modify(true);
            Message('%1', Setup."Last Connection Result");
            exit;
        end;

        ErrorText := GetLastErrorText();
        if ErrorText = '' then
            ErrorText := 'The SharePoint archive connection test failed.';
        Setup."Last Connection Result" := CopyStr(ErrorText, 1, MaxStrLen(Setup."Last Connection Result"));
        Setup.Modify(true);
        Error('%1', ErrorText);
    end;

    procedure ArchivePendingDocuments(var ArchivedCount: Integer; var FailedCount: Integer)
    var
        LogEntry: Record "GPI Document Delivery Log";
        EntryNos: List of [Integer];
        EntryNo: Integer;
    begin
        LogEntry.SetRange(Status, LogEntry.Status::Sent);
        LogEntry.SetFilter("Archive Status", '%1|%2', LogEntry."Archive Status"::Pending, LogEntry."Archive Status"::Failed);
        if LogEntry.FindSet() then
            repeat
                EntryNos.Add(LogEntry."Entry No.");
            until (LogEntry.Next() = 0) or (EntryNos.Count() >= 250);

        foreach EntryNo in EntryNos do
            if LogEntry.Get(EntryNo) then begin
                LogEntry.CalcFields("Document Content");
                if LogEntry."Document Content".HasValue then begin
                    ArchiveDeliveryLog(LogEntry);
                    if LogEntry."Archive Status" = LogEntry."Archive Status"::Archived then
                        ArchivedCount += 1
                    else
                        FailedCount += 1;
                    Commit();
                end;
            end;
    end;

    procedure GetArchiveAccount(var AccountName: Text; var ConnectorName: Text): Boolean
    var
        FileScenario: Codeunit "File Scenario";
        TempAccount: Record "File Account" temporary;
    begin
        if not FileScenario.GetSpecificFileAccount(Enum::"File Scenario"::"GPI Document Archive", TempAccount) then
            exit(false);
        AccountName := TempAccount.Name;
        ConnectorName := Format(TempAccount.Connector);
        exit(true);
    end;

    procedure GetSetup(var Setup: Record "GPI SharePoint Archive Setup")
    begin
        if Setup.Get('SETUP') then
            exit;
        Setup.Init();
        Setup."Primary Key" := 'SETUP';
        Setup.Insert(true);
    end;

    [TryFunction]
    local procedure TryArchive(var LogEntry: Record "GPI Document Delivery Log"; Setup: Record "GPI SharePoint Archive Setup"; var ArchivePath: Text; var ArchiveFileName: Text[250])
    var
        Storage: Codeunit "External File Storage";
        FileScenario: Codeunit "File Scenario";
        TempAccount: Record "File Account" temporary;
        PdfStream: InStream;
        ParentPath: Text;
    begin
        if not FileScenario.GetSpecificFileAccount(Enum::"File Scenario"::"GPI Document Archive", TempAccount) then
            Error('Assign GPI Document Archive to a SharePoint External File Account.');
        Storage.Initialize(TempAccount);

        LogEntry.CalcFields("Document Content");
        if not LogEntry."Document Content".HasValue then
            Error('No PDF is stored for delivery log entry %1.', LogEntry."Entry No.");

        ParentPath := PathMgt.BuildParentPath(Storage, LogEntry, Setup);
        ArchiveFileName := PathMgt.GetUniqueFileName(Storage, ParentPath, LogEntry."Attachment Filename", LogEntry."Entry No.");
        ArchivePath := Storage.CombinePath(ParentPath, ArchiveFileName);
        LogEntry."Document Content".CreateInStream(PdfStream);
        if not Storage.CreateFile(ArchivePath, PdfStream) then
            Error('%1', GetLastErrorText());
    end;

    [TryFunction]
    local procedure TryConnection(Setup: Record "GPI SharePoint Archive Setup"; var AccountName: Text)
    var
        Storage: Codeunit "External File Storage";
        FileScenario: Codeunit "File Scenario";
        TempAccount: Record "File Account" temporary;
    begin
        if not FileScenario.GetSpecificFileAccount(Enum::"File Scenario"::"GPI Document Archive", TempAccount) then
            Error('Assign GPI Document Archive to a SharePoint External File Account before testing.');
        AccountName := TempAccount.Name;
        Storage.Initialize(TempAccount);
        if not Storage.DirectoryExists('') then
            Error('The SharePoint archive root could not be accessed.');
    end;

    var
        PathMgt: Codeunit "GPI Archive Path Mgt.";
}
