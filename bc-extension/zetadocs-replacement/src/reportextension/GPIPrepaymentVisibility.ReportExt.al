reportextension 70511 "GPI Prepayment Visibility" extends "GPI Prepayment Notice"
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
