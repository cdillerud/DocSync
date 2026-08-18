permissionset 70691 "GPI COMM GUARD POC"
{
    Assignable = true;
    Caption = 'GPI Commercial Guardrails POC';

    Permissions =
        tabledata Item = R,
        tabledata "Item Unit of Measure" = R,
        tabledata "Sales Invoice Header" = R,
        tabledata "Sales Invoice Line" = R,
        tabledata "GPI Pricing Guardrail" = R,
        query "GPI Commercial Hist Sales" = X,
        query "GPI Item Cost Context" = X,
        page "GPI Pricing Guardrail API" = X;
}
