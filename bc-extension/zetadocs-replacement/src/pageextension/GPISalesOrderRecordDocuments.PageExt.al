pageextension 70623 "GPI Sales Order Record Docs" extends "Sales Order"
{
    layout
    {
        addafter(Page50004)
        {
            part(GPIRecordDocuments; "GPI Record Documents FactBox")
            {
                ApplicationArea = All;
                Caption = 'Gamer Documents';
            }
        }
    }

    trigger OnAfterGetCurrRecord()
    begin
        CurrPage.GPIRecordDocuments.Page.SetSourceContext(
            Database::"Sales Header",
            Rec.SystemId,
            'Sales Order',
            Rec."No.",
            'Customer',
            Rec."Sell-to Customer No.",
            Rec."Sell-to Customer No.",
            '',
            Rec."Location Code");
    end;
}