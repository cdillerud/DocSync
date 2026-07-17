pageextension 70628 "GPI Transfer Order Record Docs" extends "Transfer Order"
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
            Database::"Transfer Header",
            Rec.SystemId,
            'Transfer Order',
            Rec."No.",
            'Location',
            Rec."Transfer-from Code",
            '',
            '',
            Rec."Transfer-from Code");
    end;
}
