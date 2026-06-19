reportextension 70513 "GPI Blanket Visibility" extends "GPI Blanket Sales Order"
{
    dataset
    {
        modify(SalesHeader)
        {
            trigger OnBeforeAfterGetRecord()
            begin
                VisibilityMgt.ValidateSalesExternalDocument(SalesHeader);
            end;
        }

        modify(SalesLine)
        {
            trigger OnBeforeAfterGetRecord()
            begin
                if not VisibilityMgt.ShouldPrintSalesLine(SalesLine, false) then
                    CurrReport.Skip();
            end;
        }
    }

    var
        VisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
}
