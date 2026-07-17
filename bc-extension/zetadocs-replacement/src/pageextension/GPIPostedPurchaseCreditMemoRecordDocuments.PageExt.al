pageextension 70632 "GPI Posted Purch CM Rec Docs" extends "Posted Purchase Credit Memo"
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
            Database::"Purch. Cr. Memo Hdr.",
            Rec.SystemId,
            'Posted Purchase Credit Memo',
            Rec."No.",
            'Vendor',
            Rec."Buy-from Vendor No.",
            '',
            Rec."Buy-from Vendor No.",
            Rec."Location Code");
    end;
}
