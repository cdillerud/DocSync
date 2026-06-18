permissionset 70510 "GPI DOC EMAIL"
{
    Assignable = true;
    Caption = 'GPI Document Email';

    Permissions =
        tabledata "GPI Document Delivery Log" = RIMD,
        table "GPI Document Delivery Log" = X,
        page "GPI Document Delivery Log" = X,
        tabledata "GPI Document Routing Rule" = RIMD,
        table "GPI Document Routing Rule" = X,
        page "GPI Document Routing Rules" = X,
        page "GPI Posted Invoice Queue" = X,
        codeunit "GPI Sales Order Email" = X,
        codeunit "GPI Invoice Batch Email" = X,
        codeunit "GPI Blanket Sales Order Email" = X,
        codeunit "GPI Drop Ship PO Email" = X,
        codeunit "GPI Warehouse PO Email" = X,
        codeunit "GPI WH Receiving Email" = X,
        codeunit "GPI Document Policy Mgt." = X,
        report "GPI Sales Order Confirmation" = X,
        report "GPI Prepayment Notice" = X,
        report "GPI Pick Ticket" = X,
        report "GPI Blanket Sales Order" = X,
        report "GPI Drop Ship Purchase Order" = X,
        report "GPI Warehouse Purchase Order" = X,
        report "GPI Warehouse Receiving Notice" = X;
}