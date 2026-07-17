pageextension 70624 "GPI Blanket SO Record Docs" extends "Blanket Sales Order"
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
            'Blanket Sales Order',
            Rec."No.",
            'Customer',
            Rec."Sell-to Customer No.",
            Rec."Sell-to Customer No.",
            '',
            Rec."Location Code");
    end;
}
