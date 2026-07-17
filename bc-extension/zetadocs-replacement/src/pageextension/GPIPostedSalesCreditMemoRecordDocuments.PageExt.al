pageextension 70630 "GPI Posted Sales CM Rec Docs" extends "Posted Sales Credit Memo"
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
            Database::"Sales Cr.Memo Header",
            Rec.SystemId,
            'Posted Sales Credit Memo',
            Rec."No.",
            'Customer',
            Rec."Sell-to Customer No.",
            Rec."Sell-to Customer No.",
            '',
            Rec."Location Code");
    end;
}
