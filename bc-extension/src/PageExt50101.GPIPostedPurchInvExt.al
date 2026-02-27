/// <summary>
/// Page Extension 50101 "GPI Posted Purch Inv Extension"
/// Adds the GPI Documents factbox to the Posted Purchase Invoice page.
/// Position: After Summary, before Documents.
/// </summary>
pageextension 50101 "GPI Posted Purch Inv Extension" extends "Posted Purchase Invoice"
{
    layout
    {
        // Position factbox after Summary - appears between Summary and Documents
        addafter("PurchaseDocCheckFactbox")
        {
            part(GPIDocuments; "GPI Document Link Factbox")
            {
                ApplicationArea = All;
                Caption = 'GPI Documents';
                SubPageLink = "Document Type" = const("Posted Purchase Invoice"),
                              "Target SystemId" = field(SystemId);
                UpdatePropagation = Both;
            }
        }
    }
}
