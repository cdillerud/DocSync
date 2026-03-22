/// <summary>
/// Page Extension 50104 "GPI Purch Order Extension"
/// Adds the GPI Documents factbox to the Purchase Order page.
/// Enables viewing linked documents, uploading new files, and removing links.
/// </summary>
pageextension 50104 "GPI Purch Order Extension" extends "Purchase Order"
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
        VendorCtx: Text;
    begin
        // Pass vendor context for folder routing fallback
        if Rec."Buy-from Vendor Name" <> '' then
            VendorCtx := Rec."Buy-from Vendor Name";
        CurrPage.GPIDocuments.Page.SetContext(
            "GPI Doc Link Type"::"Purchase Order",
            Rec."No.",
            VendorCtx
        );
    end;
}
