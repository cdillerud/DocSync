codeunit 70702 "GPI Transfer Visibility Tests"
{
    Subtype = Test;

    [Test]
    procedure BothDocumentsAreVisibleOnBothReports()
    var
        VisibilityMgt: Codeunit "GPI Transfer Visibility Mgt.";
        TransferLine: Record "Transfer Line" temporary;
    begin
        TransferLine."GPI Transfer Visibility" := TransferLine."GPI Transfer Visibility"::"Both Transfer Documents";
        AssertTrue(VisibilityMgt.ShouldPrintOnPickList(TransferLine), 'Expected pick-list visibility.');
        AssertTrue(VisibilityMgt.ShouldPrintOnReceiptNotice(TransferLine), 'Expected receipt-notice visibility.');
    end;

    [Test]
    procedure PickOnlyIsVisibleOnlyOnPickList()
    var
        VisibilityMgt: Codeunit "GPI Transfer Visibility Mgt.";
        TransferLine: Record "Transfer Line" temporary;
    begin
        TransferLine."GPI Transfer Visibility" := TransferLine."GPI Transfer Visibility"::"Pick List Only";
        AssertTrue(VisibilityMgt.ShouldPrintOnPickList(TransferLine), 'Expected pick-list visibility.');
        AssertFalse(VisibilityMgt.ShouldPrintOnReceiptNotice(TransferLine), 'Receipt-notice visibility was not expected.');
    end;

    [Test]
    procedure ReceiptOnlyIsVisibleOnlyOnReceiptNotice()
    var
        VisibilityMgt: Codeunit "GPI Transfer Visibility Mgt.";
        TransferLine: Record "Transfer Line" temporary;
    begin
        TransferLine."GPI Transfer Visibility" := TransferLine."GPI Transfer Visibility"::"Receipt Notification Only";
        AssertFalse(VisibilityMgt.ShouldPrintOnPickList(TransferLine), 'Pick-list visibility was not expected.');
        AssertTrue(VisibilityMgt.ShouldPrintOnReceiptNotice(TransferLine), 'Expected receipt-notice visibility.');
    end;

    [Test]
    procedure HiddenLineIsVisibleOnNeitherReport()
    var
        VisibilityMgt: Codeunit "GPI Transfer Visibility Mgt.";
        TransferLine: Record "Transfer Line" temporary;
    begin
        TransferLine."GPI Transfer Visibility" := TransferLine."GPI Transfer Visibility"::"Do Not Print";
        AssertFalse(VisibilityMgt.ShouldPrintOnPickList(TransferLine), 'Pick-list visibility was not expected.');
        AssertFalse(VisibilityMgt.ShouldPrintOnReceiptNotice(TransferLine), 'Receipt-notice visibility was not expected.');
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
}
