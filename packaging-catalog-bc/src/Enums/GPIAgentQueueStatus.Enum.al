enum 71122 "GPI Agent Queue Status"
{
    Extensible = true;
    Caption = 'GPI Agent Queue Status';

    value(0; Pending)
    {
        Caption = 'Pending';
    }
    value(10; Processing)
    {
        Caption = 'Processing';
    }
    value(20; Completed)
    {
        Caption = 'Completed';
    }
    value(30; Failed)
    {
        Caption = 'Failed';
    }
    value(40; Cancelled)
    {
        Caption = 'Cancelled';
    }
}
