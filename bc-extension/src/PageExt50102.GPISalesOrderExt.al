/// <summary>
/// Page Extension 50102 "GPI Sales Order Extension"
/// Adds the GPI Documents factbox to the Sales Order page.
/// Supports viewing, uploading, and removing document links.
/// </summary>
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
                UpdatePropagation = Both;
            }
        }
    }

    trigger OnAfterGetCurrRecord()
    var
        CustomerCtx: Text;
    begin
        if Rec."Sell-to Customer Name" <> '' then
            CustomerCtx := Rec."Sell-to Customer Name";
        CurrPage.GPIDocuments.Page.SetContext(
            "GPI Doc Link Type"::"Sales Order",
            Rec."No.",
            CustomerCtx
        );
    end;
}
