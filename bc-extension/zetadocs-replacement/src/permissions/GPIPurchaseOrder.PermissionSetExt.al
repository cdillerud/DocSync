permissionsetextension 70513 "GPI DOC EMAIL PO" extends "GPI DOC EMAIL"
{
    Permissions =
        codeunit "GPI Drop Ship PO Email" = X,
        codeunit "GPI Warehouse PO Email" = X,
        codeunit "GPI WH Receiving Email" = X,
        report "GPI Drop Ship Purchase Order" = X,
        report "GPI Warehouse Purchase Order" = X,
        report "GPI Warehouse Receiving Notice" = X;
}
