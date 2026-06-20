codeunit 70705 "GPI Archive Path Tests"
{
    Subtype = Test;

    [Test]
    procedure CustomerSourceUsesSalesFolder()
    var
        ArchivePathMgt: Codeunit "GPI Archive Path Mgt.";
        DeliveryLog: Record "GPI Document Delivery Log" temporary;
        Setup: Record "GPI SharePoint Archive Setup" temporary;
    begin
        Setup."Sales Folder" := 'Sales';
        Setup."Purchase Folder" := 'Purchase';
        Setup."Warehouse Folder" := 'Warehouse';
        DeliveryLog."Source Table ID" := Database::Customer;

        AssertEqualText(
            'Sales',
            ArchivePathMgt.GetArchiveAreaFolder(DeliveryLog, Setup),
            'Customer-sourced documents should route to the Sales folder.');
    end;

    [Test]
    procedure PurchaseSourceUsesPurchaseFolder()
    var
        ArchivePathMgt: Codeunit "GPI Archive Path Mgt.";
        DeliveryLog: Record "GPI Document Delivery Log" temporary;
        Setup: Record "GPI SharePoint Archive Setup" temporary;
    begin
        Setup."Sales Folder" := 'Sales';
        Setup."Purchase Folder" := 'Purchasing';
        Setup."Warehouse Folder" := 'Warehouse';
        DeliveryLog."Source Table ID" := Database::"Purchase Header";

        AssertEqualText(
            'Purchasing',
            ArchivePathMgt.GetArchiveAreaFolder(DeliveryLog, Setup),
            'Purchase documents should route to the Purchase folder.');
    end;

    [Test]
    procedure TransferSourceUsesWarehouseFolder()
    var
        ArchivePathMgt: Codeunit "GPI Archive Path Mgt.";
        DeliveryLog: Record "GPI Document Delivery Log" temporary;
        Setup: Record "GPI SharePoint Archive Setup" temporary;
    begin
        Setup."Sales Folder" := 'Sales';
        Setup."Purchase Folder" := 'Purchase';
        Setup."Warehouse Folder" := 'Transfer Warehouse';
        DeliveryLog."Source Table ID" := Database::"Transfer Header";

        AssertEqualText(
            'Transfer Warehouse',
            ArchivePathMgt.GetArchiveAreaFolder(DeliveryLog, Setup),
            'Transfer documents should route to the Warehouse folder.');
    end;

    [Test]
    procedure TransferSourceDefaultsWarehouseFolderWhenSetupIsBlank()
    var
        ArchivePathMgt: Codeunit "GPI Archive Path Mgt.";
        DeliveryLog: Record "GPI Document Delivery Log" temporary;
        Setup: Record "GPI SharePoint Archive Setup" temporary;
    begin
        DeliveryLog."Source Table ID" := Database::"Transfer Header";

        AssertEqualText(
            'Warehouse',
            ArchivePathMgt.GetArchiveAreaFolder(DeliveryLog, Setup),
            'A blank Warehouse folder should use the Warehouse default.');
    end;

    [Test]
    procedure CompletedDateBuildsExpectedArchiveDateFolder()
    var
        ArchivePathMgt: Codeunit "GPI Archive Path Mgt.";
        DeliveryLog: Record "GPI Document Delivery Log" temporary;
    begin
        DeliveryLog."Completed Date/Time" := CreateDateTime(DMY2Date(19, 6, 2026), 123000T);

        AssertEqualText(
            '06-19-2026',
            ArchivePathMgt.GetArchiveDateFolder(DeliveryLog),
            'The archive date folder was not formatted correctly.');
    end;

    [Test]
    procedure PathSegmentSanitizesSharePointInvalidCharacters()
    var
        ArchivePathMgt: Codeunit "GPI Archive Path Mgt.";
    begin
        AssertEqualText(
            'A_B_C_D_E_F_G_H_I_J_K',
            ArchivePathMgt.SanitizePathSegment('A/B:C*D?E"F<G>H|I#J%K'),
            'SharePoint-invalid path characters were not sanitized.');
    end;

    [Test]
    procedure WebUrlRemovesTrailingSlashAndAddsWebParameter()
    var
        ArchivePathMgt: Codeunit "GPI Archive Path Mgt.";
        Setup: Record "GPI SharePoint Archive Setup" temporary;
    begin
        Setup."SharePoint Web Base URL" := 'https://example.sharepoint.com/sites/GPI/';

        AssertEqualText(
            'https://example.sharepoint.com/sites/GPI/06-19-2026/ACME/Sales?web=1',
            ArchivePathMgt.BuildWebUrl(Setup, '06-19-2026/ACME/Sales'),
            'The SharePoint web URL was not built correctly.');
    end;

    local procedure AssertEqualText(Expected: Text; Actual: Text; FailureMessage: Text)
    begin
        if Expected <> Actual then
            Error('%1 Expected "%2" but received "%3".', FailureMessage, Expected, Actual);
    end;
}
