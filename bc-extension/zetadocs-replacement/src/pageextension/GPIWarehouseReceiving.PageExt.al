pageextension 70518 "GPI WH Receiving PO Ext" extends "Purchase Order"
{
    layout
    {
        addafter("Expected Receipt Date")
        {
            field(GPIWarehouseReceiptDate; Rec."GPI WH Receipt Date")
            {
                ApplicationArea = All;
                Caption = 'Warehouse Receipt Date';
                Importance = Promoted;
                ToolTip = 'Specifies the date the warehouse should expect to receive this purchase order.';
            }
        }
    }
}
