permissionset 70691 "GPI COMM GUARD POC"
{
    Assignable = true;
    Caption = 'GPI Commercial Guardrails POC';

    Permissions =
        tabledata "Sales Invoice Header" = R,
        tabledata "Sales Invoice Line" = R,
        query "GPI Commercial Hist Sales" = X;
}
