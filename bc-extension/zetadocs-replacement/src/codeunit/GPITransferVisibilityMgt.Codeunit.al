codeunit 70571 "GPI Transfer Visibility Mgt."
{
    procedure ShouldPrintOnPickList(TransferLine: Record "Transfer Line"): Boolean
    begin
        exit(
            TransferLine."GPI Transfer Visibility" in
            [TransferLine."GPI Transfer Visibility"::"Both Transfer Documents",
             TransferLine."GPI Transfer Visibility"::"Pick List Only"]);
    end;

    procedure ShouldPrintOnReceiptNotice(TransferLine: Record "Transfer Line"): Boolean
    begin
        exit(
            TransferLine."GPI Transfer Visibility" in
            [TransferLine."GPI Transfer Visibility"::"Both Transfer Documents",
             TransferLine."GPI Transfer Visibility"::"Receipt Notification Only"]);
    end;
}
