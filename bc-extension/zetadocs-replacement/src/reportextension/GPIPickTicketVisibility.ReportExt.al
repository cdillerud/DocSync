reportextension 70512 "GPI Pick Ticket Visibility" extends "GPI Pick Ticket"
{
    dataset
    {
        modify(SalesLine)
        {
            trigger OnBeforeAfterGetRecord()
            begin
                if not VisibilityMgt.ShouldPrintSalesLine(SalesLine, true) then
                    CurrReport.Skip();
            end;
        }
    }

    var
        VisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
}
