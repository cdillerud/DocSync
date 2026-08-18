permissionset 71000 "GPI PACK CATALOG"
{
    Assignable = true;
    Caption = 'GPI Packaging Catalog';

    Permissions =
        tabledata "GPI Pack Product" = RIMD,
        tabledata "GPI Pack Vendor Loc" = RIMD,
        tabledata "GPI Pack Price Hist" = R,
        tabledata "GPI Pack Frt Rate" = RIMD,
        page "GPI Pack Prod Card" = X,
        page "GPI Pack Products" = X,
        page "GPI Pack Vendor Locs" = X,
        page "GPI Pack Price Hist" = X,
        page "GPI Pack Frt Rates" = X,
        codeunit "GPI Pack Catalog Mgt" = X;
}
