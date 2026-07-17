pageextension 70629 "GPI Posted Sales Inv Rec Docs" extends "Posted Sales Invoice"
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
            Database::"Sales Invoice Header",
            Rec.SystemId,
            'Posted Sales Invoice',
            Rec."No.",
            'Customer',
            Rec."Sell-to Customer No.",
            Rec."Sell-to Customer No.",
            '',
            Rec."Location Code");
    end;
}
