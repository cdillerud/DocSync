enum 70511 "GPI Delivery Status"
{
    Extensible = true;
    Caption = 'GPI Delivery Status';

    value(0; Created)
    {
        Caption = 'Created';
    }

    value(1; "Saved As Draft")
    {
        Caption = 'Saved As Draft';
    }

    value(2; Sent)
    {
        Caption = 'Sent';
    }

    value(3; Discarded)
    {
        Caption = 'Discarded';
    }

    value(4; Failed)
    {
        Caption = 'Failed';
    }

    value(5; Archived)
    {
        Caption = 'Archived';
    }

    value(6; Ready)
    {
        Caption = 'Ready';
    }

    value(7; "Missing Recipient")
    {
        Caption = 'Missing Recipient';
    }
}
