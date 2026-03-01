/// <summary>
/// Page Extension 50102 "GPI Sales Order Extension"
/// Adds the GPI Documents factbox to the Sales Order page.
/// Position: First in factbox area (top).
/// </summary>
pageextension 50102 "GPI Sales Order Extension" extends "Sales Order"
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
                SubPageLink = "Document Type" = const("Sales Order"),
                              "Target SystemId" = field(SystemId);
                UpdatePropagation = Both;
            }
        }
    }
}
