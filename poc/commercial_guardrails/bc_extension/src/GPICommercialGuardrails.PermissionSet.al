permissionset 70691 "GPI COMM GUARD POC"
{
    Assignable = true;
    Caption = 'GPI Commercial Guardrails POC';

    Permissions =
        tabledata "Sales Invoice Header" = R,
        tabledata "Sales Invoice Line" = R,
        tabledata "GPI Pricing Guardrail" = R,
        query "GPI Commercial Hist Sales" = X,
        page "GPI Pricing Guardrail API" = X;
}
