permissionset 70620 "GPI RECORD DOCUMENTS"
{
    Assignable = true;
    Caption = 'GPI Record Documents';

    Permissions =
        tabledata "GPI Record Document" = RIMD,
        tabledata "GPI Document Delivery Log" = R,
        table "GPI Record Document" = X,
        page "GPI Record Documents FactBox" = X,
        page "GPI Record Document List" = X,
        codeunit "GPI Record Document Mgt." = X,
        codeunit "GPI Record Document Path Mgt." = X;
}