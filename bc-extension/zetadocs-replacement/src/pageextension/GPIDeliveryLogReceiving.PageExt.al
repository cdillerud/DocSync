pageextension 70519 "GPI Delivery Log Receiving" extends "GPI Document Delivery Log"
{
    actions
    {
        addafter(OpenSourceDocument)
        {
            action(OpenReceivingPurchaseOrder)
            {
                ApplicationArea = All;
                Caption = 'Open Receiving Purchase Order';
                Image = Document;
                Visible = IsWarehouseReceivingNotice;
                ToolTip = 'Opens the Purchase Order related to this warehouse receiving notice.';

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
        IsWarehouseReceivingNotice := Rec."Delivery Document Type" = Rec."Delivery Document Type"::"Warehouse Receiving Notice";
    end;

    var
        IsWarehouseReceivingNotice: Boolean;
}
