codeunit 70701 "GPI Line Visibility Tests"
{
    Subtype = Test;

    [Test]
    procedure AllDocumentsPrintsOnExternalAndWarehouseReports()
    var
        VisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        SalesLine: Record "Sales Line" temporary;
    begin
        SalesLine."GPI Document Visibility" := SalesLine."GPI Document Visibility"::"All Documents";

        AssertTrue(
            VisibilityMgt.ShouldPrintSalesLine(SalesLine, false),
            'All Documents should print on customer-facing reports.');
        AssertTrue(
            VisibilityMgt.ShouldPrintSalesLine(SalesLine, true),
            'All Documents should print on warehouse reports.');
    end;

    [Test]
    procedure CustomerOnlyPrintsOnlyOnExternalReports()
    var
        VisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        SalesLine: Record "Sales Line" temporary;
    begin
        SalesLine."GPI Document Visibility" := SalesLine."GPI Document Visibility"::"Customer/Vendor Documents Only";

        AssertTrue(
            VisibilityMgt.ShouldPrintSalesLine(SalesLine, false),
            'Customer/Vendor Documents Only should print externally.');
        AssertFalse(
            VisibilityMgt.ShouldPrintSalesLine(SalesLine, true),
            'Customer/Vendor Documents Only should not print on warehouse reports.');
    end;

    [Test]
    procedure WarehouseOnlyPrintsOnlyOnWarehouseReports()
    var
        VisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        PurchaseLine: Record "Purchase Line" temporary;
    begin
        PurchaseLine."GPI Document Visibility" := PurchaseLine."GPI Document Visibility"::"Warehouse Documents Only";

        AssertFalse(
            VisibilityMgt.ShouldPrintPurchaseLine(PurchaseLine, false),
            'Warehouse Documents Only should not print externally.');
        AssertTrue(
            VisibilityMgt.ShouldPrintPurchaseLine(PurchaseLine, true),
            'Warehouse Documents Only should print on warehouse reports.');
    end;

    [Test]
    procedure DoNotPrintIsHiddenFromBothDocumentTypes()
    var
        VisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        SalesLine: Record "Sales Line" temporary;
    begin
        SalesLine."GPI Document Visibility" := SalesLine."GPI Document Visibility"::"Do Not Print";

        AssertFalse(
            VisibilityMgt.ShouldPrintSalesLine(SalesLine, false),
            'Do Not Print should not print externally.');
        AssertFalse(
            VisibilityMgt.ShouldPrintSalesLine(SalesLine, true),
            'Do Not Print should not print on warehouse reports.');
    end;

    [Test]
    procedure HiddenZeroAmountLineIsAllowed()
    var
        VisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        Visibility: Enum "GPI Document Visibility";
    begin
        Visibility := Visibility::"Do Not Print";

        VisibilityMgt.ValidateFinancialLineVisibility(0, Visibility);
    end;

    [Test]
    procedure HiddenNonzeroFinancialLineRaisesExpectedError()
    var
        VisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        Visibility: Enum "GPI Document Visibility";
    begin
        Visibility := Visibility::"Warehouse Documents Only";

        AssertError VisibilityMgt.ValidateFinancialLineVisibility(125.50, Visibility);
        AssertContains(
            GetLastErrorText(),
            'financial lines must appear',
            'The financial-line visibility error was not returned.');
    end;

    local procedure AssertTrue(Condition: Boolean; FailureMessage: Text)
    begin
        if not Condition then
            Error('%1', FailureMessage);
    end;

    local procedure AssertFalse(Condition: Boolean; FailureMessage: Text)
    begin
        if Condition then
            Error('%1', FailureMessage);
    end;

    local procedure AssertContains(ActualText: Text; ExpectedFragment: Text; FailureMessage: Text)
    begin
        if StrPos(LowerCase(ActualText), LowerCase(ExpectedFragment)) = 0 then
            Error('%1 Actual error: %2', FailureMessage, ActualText);
    end;
}
