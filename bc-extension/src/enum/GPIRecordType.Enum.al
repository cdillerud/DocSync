enum 50100 "GPI Record Type"
{
    Extensible = true;
    Caption = 'GPI Record Type';

    value(0; " ")
    {
        Caption = ' ';
    }
    value(1; "Sales Order")
    {
        Caption = 'Sales Order';
    }
    value(2; "Purchase Invoice")
    {
        Caption = 'Purchase Invoice';
    }
    value(3; Customer)
    {
        Caption = 'Customer';
    }
    value(4; Vendor)
    {
        Caption = 'Vendor';
    }
    value(5; Company)
    {
        Caption = 'Company';
    }
}
