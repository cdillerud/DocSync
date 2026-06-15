permissionset 70150000 "GPI DOC DELIVERY"
{
    Assignable = true;
    Caption = 'GPI Document Delivery';

    Permissions =
        tabledata "GPI Doc Delivery Setup" = RIMD,
        tabledata "GPI Doc Delivery Log" = RIMD,
        tabledata "GPI Delivery Preview Buffer" = RIMD,
        table "GPI Doc Delivery Setup" = X,
        table "GPI Doc Delivery Log" = X,
        table "GPI Delivery Preview Buffer" = X,
        page "GPI Doc Delivery Setup" = X,
        page "GPI Doc Delivery Log" = X,
        page "GPI Delivery Preview" = X,
        codeunit "GPI Hub Event Builder" = X,
        codeunit "GPI Hub Client" = X,
        codeunit "GPI Doc Delivery Test" = X,
        codeunit "GPI Posted Sales Inv Bridge" = X,
        codeunit "GPI Posted Purch Inv Bridge" = X,
        codeunit "GPI Sales Cr Memo Bridge" = X,
        codeunit "GPI Purch Cr Memo Bridge" = X,
        codeunit "GPI SO Confirm Preflight" = X;
}
