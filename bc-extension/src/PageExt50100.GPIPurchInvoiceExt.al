/// <summary>
/// Page Extension 50100 "GPI Purch Invoice Extension"
/// Adds the GPI Documents factbox to the Purchase Invoice page.
/// Supports viewing, uploading, and removing document links.
/// </summary>
pageextension 50100 "GPI Purch Invoice Extension" extends "Purchase Invoice"
{
    layout
    {
        addafter("PurchaseDocCheckFactbox")
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
            "GPI Doc Link Type"::"Purchase Invoice",
            Rec."No.",
            VendorCtx
        );
    end;
}
