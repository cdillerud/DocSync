pageextension 70622 "GPI Vendor Record Documents" extends "Vendor Card"
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
            Database::Vendor,
            Rec.SystemId,
            'Vendor',
            Rec."No.",
            'Vendor',
            Rec."No.",
            '',
            Rec."No.",
            '');
    end;
}
