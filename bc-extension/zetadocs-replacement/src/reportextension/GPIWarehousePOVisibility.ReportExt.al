reportextension 70515 "GPI Warehouse PO Visibility" extends "GPI Warehouse Purchase Order"
{
    dataset
    {
        modify(PurchaseHeader)
        {
            trigger OnBeforeAfterGetRecord()
            begin
                VisibilityMgt.ValidatePurchaseExternalDocument(PurchaseHeader);
            end;
        }

        modify(PurchaseLine)
        {
            trigger OnBeforeAfterGetRecord()
            begin
                if not VisibilityMgt.ShouldPrintPurchaseLine(PurchaseLine, false) then
                    CurrReport.Skip();
            end;
        }
    }

    var
        VisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
}
