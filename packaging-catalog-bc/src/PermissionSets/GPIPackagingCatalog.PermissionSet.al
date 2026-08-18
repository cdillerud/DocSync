permissionset 71000 "GPI PACK CATALOG"
{
    Assignable = true;
    Caption = 'GPI Packaging Catalog';

    Permissions =
        tabledata Item = R,
        tabledata "Item Unit of Measure" = R,
        tabledata "Sales Invoice Header" = R,
        tabledata "Sales Invoice Line" = R,
        tabledata "GPI Pack Product" = RIMD,
        tabledata "GPI Pack Vendor Loc" = RIMD,
        tabledata "GPI Pack Price Hist" = R,
        tabledata "GPI Pack Frt Rate" = RIMD,
        tabledata "GPI Pack Cost Work" = RIMD,
        tabledata "GPI Pricing Guard" = RIMD,
        table "GPI Pricing Guard" = X,
        page "GPI Pack Prod Card" = X,
        page "GPI Pack Products" = X,
        page "GPI Pack Vendor Locs" = X,
        page "GPI Pack Price Hist" = X,
        page "GPI Pack Frt Rates" = X,
        page "GPI Pack Cost Works" = X,
        page "GPI Pack Cost Calc" = X,
        page "GPI Pricing Guards" = X,
        page "GPI Pricing GuardAPI" = X,
        query "GPI Comm Hist Sales" = X,
        query "GPI Item Cost Ctx" = X,
        codeunit "GPI Pack Catalog Mgt" = X,
        codeunit "GPI Pack Cost Mgt" = X;
}
