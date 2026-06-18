codeunit 70521 "GPI Linked Document Path Mgt."
{
    procedure BuildParentPath(var Storage: Codeunit "External File Storage"; Setup: Record "GPI SharePoint Archive Setup"; UploadDate: Date; PartyName: Text; BusinessArea: Text): Text
    var
        ParentPath: Text;
        AreaFolder: Text;
        DateFolder: Text;
    begin
        DateFolder := Format(UploadDate, 0, '<Month,2>-<Day,2>-<Year4>');

        if Setup."Root Folder" <> '' then begin
            EnsureDirectory(Storage, Setup."Root Folder");
            ParentPath := Storage.CombinePath(Setup."Root Folder", DateFolder);
        end else
            ParentPath := DateFolder;

        EnsureDirectory(Storage, ParentPath);
        ParentPath := Storage.CombinePath(ParentPath, SanitizeSegment(PartyName));
        EnsureDirectory(Storage, ParentPath);

        if LowerCase(BusinessArea) = 'purchase' then
            AreaFolder := Setup."Purchase Folder"
        else
            AreaFolder := Setup."Sales Folder";

        ParentPath := Storage.CombinePath(ParentPath, SanitizeSegment(AreaFolder));
        EnsureDirectory(Storage, ParentPath);
        exit(ParentPath);
    end;

    procedure GetUniqueFileName(var Storage: Codeunit "External File Storage"; ParentPath: Text; RequestedName: Text; EntryNo: Integer): Text[250]
    var
        Candidate: Text[250];
        BaseName: Text;
        Extension: Text;
        Counter: Integer;
    begin
        Candidate := CopyStr(SanitizeSegment(RequestedName), 1, MaxStrLen(Candidate));
        if Candidate = '' then
            Candidate := CopyStr(StrSubstNo('GPI-Document-%1', EntryNo), 1, MaxStrLen(Candidate));

        if not Storage.FileExists(Storage.CombinePath(ParentPath, Candidate)) then
            exit(Candidate);

        SplitFileName(Candidate, BaseName, Extension);
        for Counter := 1 to 999 do begin
            Candidate := CopyStr(StrSubstNo('%1(%2)%3', BaseName, Counter, Extension), 1, MaxStrLen(Candidate));
            if not Storage.FileExists(Storage.CombinePath(ParentPath, Candidate)) then
                exit(Candidate);
        end;

        Error('A unique SharePoint filename could not be generated for %1.', RequestedName);
    end;

    procedure BuildWebUrl(Setup: Record "GPI SharePoint Archive Setup"; ArchivePath: Text): Text
    var
        BaseUrl: Text;
    begin
        BaseUrl := DelChr(Setup."SharePoint Web Base URL", '>', '/');
        if BaseUrl = '' then
            exit('');
        exit(StrSubstNo('%1/%2?web=1', BaseUrl, ArchivePath));
    end;

    local procedure EnsureDirectory(var Storage: Codeunit "External File Storage"; DirectoryPath: Text)
    begin
        if DirectoryPath = '' then
            exit;
        if Storage.DirectoryExists(DirectoryPath) then
            exit;
        if not Storage.CreateDirectory(DirectoryPath) then
            Error('%1', GetLastErrorText());
    end;

    local procedure SanitizeSegment(Value: Text): Text
    var
        SanitizedValue: Text;
    begin
        SanitizedValue := ConvertStr(Value, '\/:*?"<>|', '_________');
        SanitizedValue := ConvertStr(SanitizedValue, '#%', '__');
        SanitizedValue := DelChr(SanitizedValue, '<>', ' ');
        SanitizedValue := DelChr(SanitizedValue, '>', '.');
        if SanitizedValue = '' then
            SanitizedValue := 'Unknown';
        exit(SanitizedValue);
    end;

    local procedure SplitFileName(FileName: Text; var BaseName: Text; var Extension: Text)
    var
        Position: Integer;
        DotPosition: Integer;
    begin
        for Position := 1 to StrLen(FileName) do
            if CopyStr(FileName, Position, 1) = '.' then
                DotPosition := Position;

        if DotPosition > 1 then begin
            BaseName := CopyStr(FileName, 1, DotPosition - 1);
            Extension := CopyStr(FileName, DotPosition);
        end else begin
            BaseName := FileName;
            Extension := '';
        end;
    end;
}
