codeunit 71101 "GPI Pack Doc Mgt"
{
    procedure UploadDocument(ProductNo: Code[20]): Boolean
    var
        Product: Record "GPI Pack Product";
        ProductDoc: Record "GPI Pack Product Doc";
        InStr: InStream;
        OutStr: OutStream;
        FileName: Text;
    begin
        Product.Get(ProductNo);

        FileName := '';
#pragma warning disable AL0432
        if not UploadIntoStream(
            'Select packaging product document',
            '',
            'All Files (*.*)|*.*',
            FileName,
            InStr)
        then
            exit(false);
#pragma warning restore AL0432

        ProductDoc.Init();
        ProductDoc."Product No." := ProductNo;
        ProductDoc."File Name" := CopyStr(FileName, 1, MaxStrLen(ProductDoc."File Name"));
        ProductDoc.Description := CopyStr(FileName, 1, MaxStrLen(ProductDoc.Description));
        ProductDoc."Document Type" := InferDocumentType(FileName);
        ProductDoc."Uploaded At" := CurrentDateTime();
        ProductDoc."Uploaded By" := CopyStr(UserId(), 1, MaxStrLen(ProductDoc."Uploaded By"));
        ProductDoc.Content.CreateOutStream(OutStr);
        CopyStream(OutStr, InStr);
        ProductDoc.Insert(true);

        exit(true);
    end;

    procedure DownloadDocument(var ProductDoc: Record "GPI Pack Product Doc")
    var
        InStr: InStream;
        FileName: Text;
    begin
        ProductDoc.TestField("File Name");
        ProductDoc.CalcFields(Content);
        ProductDoc.Content.CreateInStream(InStr);
        FileName := ProductDoc."File Name";

        if not DownloadFromStream(InStr, '', '', '', FileName) then
            Error('The document could not be downloaded.');
    end;

    procedure DeleteDocument(var ProductDoc: Record "GPI Pack Product Doc")
    begin
        if not Confirm('Delete document %1?', false, ProductDoc."File Name") then
            exit;

        ProductDoc.Delete(true);
    end;

    procedure GetProductNoFromFilter(var ProductDoc: Record "GPI Pack Product Doc"): Code[20]
    var
        ProductNo: Code[20];
    begin
        ProductNo := ProductDoc."Product No.";
        if ProductNo <> '' then
            exit(ProductNo);

        if ProductDoc.GetFilter("Product No.") <> '' then
            exit(ProductDoc.GetRangeMin("Product No."));

        Error('Open product documents from a packaging product before uploading a file.');
    end;

    local procedure InferDocumentType(FileName: Text): Enum "GPI Pack Doc Type"
    var
        LowerName: Text;
    begin
        LowerName := LowerCase(FileName);

        if (StrPos(LowerName, 'draw') > 0) or
           (StrPos(LowerName, '.dwg') > 0) or
           (StrPos(LowerName, '.dxf') > 0)
        then
            exit("GPI Pack Doc Type"::Drawing);

        if (StrPos(LowerName, 'spec') > 0) or
           (StrPos(LowerName, 'datasheet') > 0) or
           (StrPos(LowerName, 'data sheet') > 0)
        then
            exit("GPI Pack Doc Type"::Specification);

        if (StrPos(LowerName, 'artwork') > 0) or
           (StrPos(LowerName, 'art proof') > 0)
        then
            exit("GPI Pack Doc Type"::Artwork);

        if (StrPos(LowerName, 'cert') > 0) or
           (StrPos(LowerName, 'coa') > 0)
        then
            exit("GPI Pack Doc Type"::Certificate);

        if (StrPos(LowerName, 'supplier') > 0) or
           (StrPos(LowerName, 'vendor') > 0)
        then
            exit("GPI Pack Doc Type"::"Supplier Document");

        exit("GPI Pack Doc Type"::Other);
    end;
}
