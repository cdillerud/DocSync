enum 71000 "GPI Pack Transport"
{
    Extensible = true;
    Caption = 'Packaging Transport Mode';

    value(0; Any)
    {
        Caption = 'Any';
    }
    value(1; TL)
    {
        Caption = 'Truckload';
    }
    value(2; CNTR)
    {
        Caption = 'Container';
    }
    value(3; Other)
    {
        Caption = 'Other';
    }
}
