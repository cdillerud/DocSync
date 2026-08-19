enum 71007 "GPI Freight Basis"
{
    Extensible = false;
    Caption = 'Packaging Freight Basis';

    value(0; None)
    {
        Caption = 'Not Calculated';
    }
    value(1; "Stored Rate")
    {
        Caption = 'Stored CWT Rate';
    }
    value(2; Mileage)
    {
        Caption = 'Route Mileage';
    }
}
