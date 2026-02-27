/// <summary>
/// Page Extension 50101 "GPI Posted Purch Inv Extension"
/// Adds the GPI Documents factbox to the Posted Purchase Invoice page.
/// Position: First in factbox area (top).
/// </summary>
pageextension 50101 "GPI Posted Purch Inv Extension" extends "Posted Purchase Invoice"
{
    layout
    {
        // Position factbox at top of factbox area
        addfirst(FactBoxes)
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
