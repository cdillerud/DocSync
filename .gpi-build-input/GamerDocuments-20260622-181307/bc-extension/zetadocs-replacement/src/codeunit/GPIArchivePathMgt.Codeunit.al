codeunit 70519 "GPI Archive Path Mgt."
{
    procedure BuildParentPath(var Storage: Codeunit "External File Storage"; LogEntry: Record "GPI Document Delivery Log"; Setup: Record "GPI SharePoint Archive Setup"): Text
    var
        ParentPath: Text;
    begin
        if Setup."Root Folder" <> '' then begin
            EnsureDirectory(Storage, Setup."Root Folder");
            ParentPath := Storage.CombinePath(Setup."Root Folder", GetArchiveDateFolder(LogEntry));
        end else
            ParentPath := GetArchiveDateFolder(LogEntry);

        EnsureDirectory(Storage, ParentPath);
        ParentPath := Storage.CombinePath(ParentPath, SanitizePathSegment(GetArchivePartyName(LogEntry)));
        EnsureDirectory(Storage, ParentPath);
        ParentPath := Storage.CombinePath(ParentPath, GetArchiveAreaFolder(LogEntry, Setup));
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
        Candidate := CopyStr(SanitizePathSegment(RequestedName), 1, MaxStrLen(Candidate));
        if Candidate = '' then
            Candidate := CopyStr(StrSubstNo('GPI-Document-%1.pdf', EntryNo), 1, MaxStrLen(Candidate));
        if not Storage.FileExists(Storage.CombinePath(ParentPath, Candidate)) then
            exit(Candidate);

        SplitFileName(Candidate, BaseName, Extension);
        for Counter := 1 to 999 do begin
            Candidate := CopyStr(StrSubstNo('%1(%2)%3', BaseName, Counter, Extension), 1, MaxStrLen(Candidate));
            if not Storage.FileExists(Storage.CombinePath(ParentPath, Candidate)) then
                exit(Candidate);
        end;
        Error('A unique archive filename could not be generated for %1.', RequestedName);
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

    procedure EnsureDirectory(var Storage: Codeunit "External File Storage"; Path: Text)
    begin
        if Path = '' then
            exit;
        if Storage.DirectoryExists(Path) then
            exit;
        if not Storage.CreateDirectory(Path) then
            Error('%1', GetLastErrorText());
    end;

    procedure GetArchiveDateFolder(LogEntry: Record "GPI Document Delivery Log"): Text
    var
        ArchiveDate: Date;
    begin
        if LogEntry."Completed Date/Time" <> 0DT then
            ArchiveDate := DT2Date(LogEntry."Completed Date/Time")
        else
            ArchiveDate := Today;
        exit(Format(ArchiveDate, 0, '<Month,2>-<Day,2>-<Year4>'));
    end;

    procedure GetArchiveAreaFolder(LogEntry: Record "GPI Document Delivery Log"; Setup: Record "GPI SharePoint Archive Setup"): Text
    var
        WarehouseFolder: Text;
    begin
        if LogEntry."Source Table ID" = Database::"Transfer Header" then begin
            WarehouseFolder := Setup."Warehouse Folder";
            if WarehouseFolder = '' then
                WarehouseFolder := 'Warehouse';
            exit(SanitizePathSegment(WarehouseFolder));
        end;

        if LogEntry."Source Table ID" in [Database::"Purchase Header", Database::"Purch. Cr. Memo Hdr."] then
            exit(SanitizePathSegment(Setup."Purchase Folder"));
        exit(SanitizePathSegment(Setup."Sales Folder"));
    end;

    procedure GetArchivePartyName(LogEntry: Record "GPI Document Delivery Log"): Text
    var
        Customer: Record Customer;
        Vendor: Record Vendor;
        Location: Record Location;
    begin
        case LogEntry."Source Party Type" of
            'Customer':
                if Customer.Get(LogEntry."Source Party No.") then
                    exit(Customer.Name);
            'Vendor':
                if Vendor.Get(LogEntry."Source Party No.") then
                    exit(Vendor.Name);
            'Location':
                if Location.Get(LogEntry."Source Party No.") then
                    exit(Location.Name);
        end;
        if LogEntry."Source Party No." <> '' then
            exit(LogEntry."Source Party No.");
        exit(LogEntry."Source Document No.");
    end;

    procedure SanitizePathSegment(Value: Text): Text
    var
        Result: Text;
    begin
        Result := ConvertStr(Value, '\/:*?"<>|', '_________');
        Result := ConvertStr(Result, '#%', '__');
        Result := DelChr(Result, '<>', ' ');
        Result := DelChr(Result, '>', '.');
        if Result = '' then
            Result := 'Unknown';
        exit(Result);
    end;

    local procedure SplitFileName(FileName: Text; var BaseName: Text; var Extension: Text)
    begin
        if (StrLen(FileName) > 4) and (LowerCase(CopyStr(FileName, StrLen(FileName) - 3, 4)) = '.pdf') then begin
            BaseName := CopyStr(FileName, 1, StrLen(FileName) - 4);
            Extension := '.pdf';
        end else begin
            BaseName := FileName;
            Extension := '';
        end;
    end;
}
