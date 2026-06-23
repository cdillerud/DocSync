enum 70513 "GPI Archive Status"
{
    Extensible = false;
    Caption = 'GPI Archive Status';

    value(0; Pending)
    {
        Caption = 'Pending';
    }

    value(1; Archived)
    {
        Caption = 'Archived';
    }

    value(2; Failed)
    {
        Caption = 'Failed';
    }

    value(3; Skipped)
    {
        Caption = 'Skipped';
    }
}
