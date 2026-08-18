permissionset 70696 "GPI COMM GUARD ADMIN"
{
    Assignable = true;
    Caption = 'GPI Commercial Guardrails Admin';

    Permissions =
        tabledata "GPI Pricing Guardrail" = RIMD,
        table "GPI Pricing Guardrail" = X,
        page "GPI Pricing Guardrails" = X;
}
