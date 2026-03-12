pageextension 50103 "GPI Posted Sales Inv Extension" extends "Posted Sales Invoice"
{
    layout
    {
        addlast(FactBoxes)
        {
            part(GPIDocuments; "GPI Document Link Factbox")
            {
                ApplicationArea = All;
                Caption = 'GPI Documents';
                SubPageLink = "Document Type" = const("Posted Sales Invoice"),
                              "Target SystemId" = field(SystemId);
            }
        }
    }
}
