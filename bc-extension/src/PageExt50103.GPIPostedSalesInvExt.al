/// <summary>
/// Page Extension 50103 "GPI Posted Sales Inv Extension"
/// Adds the GPI Documents factbox to the Posted Sales Invoice page.
/// Supports viewing, uploading, and removing document links.
/// </summary>
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
                              "BC Document No." = field("No.");
                UpdatePropagation = Both;
            }
        }
    }

    trigger OnAfterGetCurrRecord()
    begin
        CurrPage.GPIDocuments.Page.SetContext(
            "GPI Doc Link Type"::"Posted Sales Invoice",
            Rec."No.",
            ''
        );
    end;
}
