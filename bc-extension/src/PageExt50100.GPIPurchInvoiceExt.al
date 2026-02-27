/// <summary>
/// Page Extension 50100 "GPI Purch Invoice Extension"
/// Adds the GPI Documents factbox to the Purchase Invoice page.
/// Position: After Summary (PurchaseDocCheckFactbox), before Documents.
/// </summary>
pageextension 50100 "GPI Purch Invoice Extension" extends "Purchase Invoice"
{
    layout
    {
        // Position factbox after Summary (PurchaseDocCheckFactbox) - appears between Summary and Documents
        addafter("PurchaseDocCheckFactbox")
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
