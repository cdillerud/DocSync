/// <summary>
/// Page Extension 50100 "GPI Purch Invoice Extension"
/// Adds the GPI Documents factbox to the Purchase Invoice page.
/// </summary>
pageextension 50100 "GPI Purch Invoice Extension" extends "Purchase Invoice"
{
    layout
    {
        addlast(FactBoxes)
        {
            part(GPIDocuments; "GPI Document Link Factbox")
            {
                ApplicationArea = All;
                Caption = 'GPI Documents';
                SubPageLink = "Document Type" = const("Purchase Invoice"),
                              "Target SystemId" = field(SystemId);
                UpdatePropagation = Both;
            }
        }
    }
}
