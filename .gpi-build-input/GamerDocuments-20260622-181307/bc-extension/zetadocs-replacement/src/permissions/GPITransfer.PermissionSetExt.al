permissionsetextension 70570 "GPI TRANSFER DOCS" extends "GPI DOC EMAIL"
{
    Permissions =
        tabledata "Transfer Header" = r,
        tabledata "Transfer Line" = r,
        codeunit "GPI Transfer Email" = X,
        codeunit "GPI Transfer Visibility Mgt." = X,
        report "GPI Transfer Pick List" = X,
        report "GPI Transfer Receipt Notice" = X;
}
