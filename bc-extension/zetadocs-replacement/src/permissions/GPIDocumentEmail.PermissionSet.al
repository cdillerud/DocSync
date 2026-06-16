permissionset 70510 "GPI DOC EMAIL"
{
    Assignable = true;
    Caption = 'GPI Document Email';

    Permissions =
        codeunit "GPI Sales Order Email" = X,
        report "GPI Sales Order Confirmation" = X;
}
