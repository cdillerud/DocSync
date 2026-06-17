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
        codeunit "GPI Sales Order Email" = X,
        report "GPI Sales Order Confirmation" = X,
        report "GPI Prepayment Notice" = X,
        report "GPI Pick Ticket" = X;
}
