pageextension 70626 "GPI Purchase Order Record Docs" extends "Purchase Order"
{
    layout
    {
        addafter("Purchase Order Documents Sent")
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
            'Purchase Order',
            Rec."No.",
            'Vendor',
            Rec."Buy-from Vendor No.",
            '',
            Rec."Buy-from Vendor No.",
            Rec."Location Code");
    end;
}
