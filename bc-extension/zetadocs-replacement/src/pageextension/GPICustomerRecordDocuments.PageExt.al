pageextension 70621 "GPI Customer Record Documents" extends "Customer Card"
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
            Database::Customer,
            Rec.SystemId,
            'Customer',
            Rec."No.",
            'Customer',
            Rec."No.",
            Rec."No.",
            '',
            '');
    end;
}
