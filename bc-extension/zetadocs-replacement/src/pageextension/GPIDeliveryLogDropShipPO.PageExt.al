pageextension 70515 "GPI Delivery Log Drop Ship PO" extends "GPI Document Delivery Log"
{
    actions
    {
        addafter(OpenSourceDocument)
        {
            action(OpenDropShipPurchaseOrder)
            {
                ApplicationArea = All;
                Caption = 'Open Purchase Order';
                Image = Document;
                Visible = IsDropShipPurchaseOrder;
                ToolTip = 'Opens the Purchase Order related to this delivery entry.';

                trigger OnAction()
                var
                    PurchaseHeader: Record "Purchase Header";
                begin
                    if not PurchaseHeader.Get(PurchaseHeader."Document Type"::Order, Rec."Source Document No.") then
                        Error('Purchase Order %1 could not be found.', Rec."Source Document No.");

                    Page.Run(Page::"Purchase Order", PurchaseHeader);
                end;
            }
        }
    }

    trigger OnAfterGetRecord()
    begin
        IsDropShipPurchaseOrder := Rec."Delivery Document Type" = Rec."Delivery Document Type"::"Purchase Order - Drop Ship";
    end;

    var
        IsDropShipPurchaseOrder: Boolean;
}
