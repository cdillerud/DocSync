reportextension 70516 "GPI Receiving Visibility" extends "GPI Warehouse Receiving Notice"
{
    dataset
    {
        modify(PurchaseLine)
        {
            trigger OnBeforeAfterGetRecord()
            begin
                if not VisibilityMgt.ShouldPrintPurchaseLine(PurchaseLine, true) then
                    CurrReport.Skip();
            end;
        }
    }

    var
        VisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
}
