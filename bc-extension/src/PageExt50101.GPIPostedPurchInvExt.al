/// <summary>
/// Page Extension 50101 "GPI Posted Purch Inv Extension"
/// Adds the GPI Documents factbox to the Posted Purchase Invoice page.
/// Supports viewing, uploading, and removing document links.
/// </summary>
pageextension 50101 "GPI Posted Purch Inv Extension" extends "Posted Purchase Invoice"
{
    layout
    {
        addfirst(FactBoxes)
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
        if Rec."Buy-from Vendor Name" <> '' then
            VendorCtx := Rec."Buy-from Vendor Name";
        CurrPage.GPIDocuments.Page.SetContext(
            "GPI Doc Link Type"::"Posted Purchase Invoice",
            Rec."No.",
            VendorCtx
        );
    end;
}
