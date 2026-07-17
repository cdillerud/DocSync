pageextension 70625 "GPI Sales Return Record Docs" extends "Sales Return Order"
{
    layout
    {
        addlast(FactBoxes)
        {
            part(GPIRecordDocuments; "GPI Record Documents FactBox")
            {
                ApplicationArea = All;
                Caption = 'Documents';
            }
        }
    }

    trigger OnAfterGetCurrRecord()
    begin
        CurrPage.GPIRecordDocuments.Page.SetSourceContext(
            Database::"Sales Header",
            Rec.SystemId,
            'Sales Return Order',
            Rec."No.",
            'Customer',
            Rec."Sell-to Customer No.",
            Rec."Sell-to Customer No.",
            '',
            Rec."Location Code");
    end;
}
