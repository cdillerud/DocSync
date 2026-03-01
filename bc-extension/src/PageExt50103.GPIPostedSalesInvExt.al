/// <summary>
/// Page Extension 50103 "GPI Posted Sales Inv Ext"
/// Adds the GPI Documents factbox to the Posted Sales Invoice page.
/// Position: First in factbox area (top).
/// </summary>
pageextension 50103 "GPI Posted Sales Inv Ext" extends "Posted Sales Invoice"
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
                SubPageLink = "Document Type" = const("Posted Sales Invoice"),
                              "Target SystemId" = field(SystemId);
                UpdatePropagation = Both;
            }
        }
    }
}
