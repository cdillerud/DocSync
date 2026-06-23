pageextension 70517 "GPI Delivery Log Warehouse" extends "GPI Document Delivery Log"
{
    actions
    {
        addafter(OpenSourceDocument)
        {
            action(OpenWarehousePurchaseOrder)
            {
                ApplicationArea = All;
                Caption = 'Open Warehouse Purchase Order';
                Image = Document;
                Visible = IsWarehousePurchaseOrder;
                ToolTip = 'Opens the warehouse Purchase Order related to this delivery entry.';

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
        IsWarehousePurchaseOrder := Rec."Delivery Document Type" = Rec."Delivery Document Type"::"Purchase Order - Warehouse";
    end;

    var
        IsWarehousePurchaseOrder: Boolean;
}
