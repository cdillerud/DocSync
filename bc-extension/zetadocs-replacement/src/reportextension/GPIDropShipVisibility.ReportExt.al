reportextension 70514 "GPI Drop Ship Visibility" extends "GPI Drop Ship Purchase Order"
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
