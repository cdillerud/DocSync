permissionset 71000 "GPI PACKAGING CATALOG"
{
    Assignable = true;
    Caption = 'GPI Packaging Catalog';

    Permissions =
        tabledata "GPI Packaging Product" = RIMD,
        tabledata "GPI Pack Vendor Location" = RIMD,
        tabledata "GPI Pack Price History" = R,
        tabledata "GPI Pack Freight Rate" = RIMD,
        page "GPI Packaging Product Card" = X,
        page "GPI Packaging Products" = X,
        page "GPI Pack Vendor Locations" = X,
        page "GPI Pack Price History" = X,
        page "GPI Pack Freight Rates" = X,
        codeunit "GPI Packaging Catalog Mgt." = X;
}
