codeunit 70621 "GPI Record Document Path Mgt."
{
    procedure BuildParentPath(var Storage: Codeunit "External File Storage"; Document: Record "GPI Record Document"; Setup: Record "GPI SharePoint Archive Setup"): Text
    var
        ArchivePathMgt: Codeunit "GPI Archive Path Mgt.";
        ParentPath: Text;
        RecordFolder: Text;
    begin
        if Setup."Root Folder" <> '' then begin
            ArchivePathMgt.EnsureDirectory(Storage, Setup."Root Folder");
            ParentPath := Setup."Root Folder";
        end;

        RecordFolder := Setup."Record Documents Folder";
        if RecordFolder = '' then
            RecordFolder := 'Record Documents';

        ParentPath := AddDirectory(Storage, ParentPath, ArchivePathMgt.SanitizePathSegment(RecordFolder));
        ParentPath := AddDirectory(Storage, ParentPath, GetAreaFolder(Document, Setup));
        ParentPath := AddDirectory(Storage, ParentPath, ArchivePathMgt.SanitizePathSegment(GetPartyName(Document)));
        ParentPath := AddDirectory(Storage, ParentPath, ArchivePathMgt.SanitizePathSegment(Document."Source Document Type"));
        ParentPath := AddDirectory(Storage, ParentPath, ArchivePathMgt.SanitizePathSegment(Document."Source Document No."));
        exit(ParentPath);
    end;

    procedure GetUniqueFileName(var Storage: Codeunit "External File Storage"; ParentPath: Text; RequestedName: Text; EntryNo: Integer): Text[250]
    var
        ArchivePathMgt: Codeunit "GPI Archive Path Mgt.";
        Candidate: Text[250];
        BaseName: Text;
        Extension: Text;
        Counter: Integer;
    begin
        Candidate := CopyStr(ArchivePathMgt.SanitizePathSegment(RequestedName), 1, MaxStrLen(Candidate));
        if Candidate = '' then
            Candidate := CopyStr(StrSubstNo('Record-Document-%1', EntryNo), 1, MaxStrLen(Candidate));

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

    procedure BuildWebUrl(Setup: Record "GPI SharePoint Archive Setup"; SharePointPath: Text): Text
    var
        ArchivePathMgt: Codeunit "GPI Archive Path Mgt.";
    begin
        exit(ArchivePathMgt.BuildWebUrl(Setup, SharePointPath));
    end;

    procedure GetAreaFolder(Document: Record "GPI Record Document"; Setup: Record "GPI SharePoint Archive Setup"): Text
    var
        ArchivePathMgt: Codeunit "GPI Archive Path Mgt.";
        FolderName: Text;
    begin
        case Document."Source Table ID" of
            Database::Vendor,
            Database::"Purchase Header",
            Database::"Purch. Inv. Header",
            Database::"Purch. Cr. Memo Hdr.":
                FolderName := Setup."Purchase Folder";
            Database::"Transfer Header":
                FolderName := Setup."Warehouse Folder";
            else
                FolderName := Setup."Sales Folder";
        end;

        if FolderName = '' then
            case Document."Source Table ID" of
                Database::Vendor,
                Database::"Purchase Header",
                Database::"Purch. Inv. Header",
                Database::"Purch. Cr. Memo Hdr.":
                    FolderName := 'Purchase';
                Database::"Transfer Header":
                    FolderName := 'Warehouse';
                else
                    FolderName := 'Sales';
            end;

        exit(ArchivePathMgt.SanitizePathSegment(FolderName));
    end;

    procedure GetPartyName(Document: Record "GPI Record Document"): Text
    var
        Customer: Record Customer;
        Vendor: Record Vendor;
        Location: Record Location;
    begin
        case Document."Source Party Type" of
            'Customer':
                if Customer.Get(Document."Source Party No.") then
                    exit(Customer.Name);
            'Vendor':
                if Vendor.Get(Document."Source Party No.") then
                    exit(Vendor.Name);
            'Location':
                if Location.Get(Document."Source Party No.") then
                    exit(Location.Name);
        end;

        if Document."Source Party No." <> '' then
            exit(Document."Source Party No.");

        exit(Document."Source Document No.");
    end;

    local procedure AddDirectory(var Storage: Codeunit "External File Storage"; ParentPath: Text; FolderName: Text): Text
    var
        ArchivePathMgt: Codeunit "GPI Archive Path Mgt.";
        NewPath: Text;
    begin
        if ParentPath = '' then
            NewPath := FolderName
        else
            NewPath := Storage.CombinePath(ParentPath, FolderName);

        ArchivePathMgt.EnsureDirectory(Storage, NewPath);
        exit(NewPath);
    end;

    local procedure SplitFileName(FileName: Text; var BaseName: Text; var Extension: Text)
    var
        CharacterNo: Integer;
        DotPosition: Integer;
    begin
        DotPosition := 0;
        for CharacterNo := StrLen(FileName) downto 1 do
            if CopyStr(FileName, CharacterNo, 1) = '.' then begin
                DotPosition := CharacterNo;
                break;
            end;

        if DotPosition <= 1 then begin
            BaseName := FileName;
            Extension := '';
            exit;
        end;

        BaseName := CopyStr(FileName, 1, DotPosition - 1);
        Extension := CopyStr(FileName, DotPosition);
    end;
}
