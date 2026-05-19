permissionset 70150000 "GPI DOC DELIVERY"
{
    Assignable = true;
    Caption = 'GPI Document Delivery';

    Permissions =
        tabledata "GPI Doc Delivery Setup" = RIMD,
        tabledata "GPI Doc Delivery Log" = RIMD,
        table "GPI Doc Delivery Setup" = X,
        table "GPI Doc Delivery Log" = X,
        page "GPI Doc Delivery Setup" = X,
        page "GPI Doc Delivery Log" = X,
        codeunit "GPI Hub Event Builder" = X,
        codeunit "GPI Hub Client" = X,
        codeunit "GPI Doc Delivery Test" = X,
        codeunit "GPI Posted Sales Inv Bridge" = X,
        codeunit "GPI Posted Purch Inv Bridge" = X;
}
