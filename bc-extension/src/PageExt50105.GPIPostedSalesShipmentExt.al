/// <summary>
/// Page Extension 50105 "GPI Posted Sales Shipment Ext"
/// Adds the GPI Documents factbox to Posted Sales Shipment for Warehouse parity.
/// This is a read/visibility surface only; it does not enable Sales intake or
/// Sales attachment writes.
/// </summary>
pageextension 50105 "GPI Posted Sales Shipment Ext" extends "Posted Sales Shipment"
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
            "GPI Doc Link Type"::"Posted Sales Shipment",
            Rec."No.",
            CustomerCtx
        );
    end;
}
