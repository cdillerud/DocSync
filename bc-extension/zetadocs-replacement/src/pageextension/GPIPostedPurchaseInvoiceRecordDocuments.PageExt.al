pageextension 70631 "GPI Posted Purch Inv Rec Docs" extends "Posted Purchase Invoice"
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
            Database::"Purch. Inv. Header",
            Rec.SystemId,
            'Posted Purchase Invoice',
            Rec."No.",
            'Vendor',
            Rec."Buy-from Vendor No.",
            '',
            Rec."Buy-from Vendor No.",
            Rec."Location Code");
    end;
}
