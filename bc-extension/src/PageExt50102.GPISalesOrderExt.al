pageextension 50102 "GPI Sales Order Extension" extends "Sales Order"
{
    layout
    {
        addlast(FactBoxes)
        {
            part(GPIDocuments; "GPI Document Link Factbox")
            {
                ApplicationArea = All;
                Caption = 'GPI Documents';
                SubPageLink = "Document Type" = const("Sales Order"),
                              "Target SystemId" = field(SystemId);
            }
        }
    }
}
