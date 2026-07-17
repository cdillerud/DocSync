pageextension 70627 "GPI Purchase Return Rec Docs" extends "Purchase Return Order"
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
            Database::"Purchase Header",
            Rec.SystemId,
            'Purchase Return Order',
            Rec."No.",
            'Vendor',
            Rec."Buy-from Vendor No.",
            '',
            Rec."Buy-from Vendor No.",
            Rec."Location Code");
    end;
}
