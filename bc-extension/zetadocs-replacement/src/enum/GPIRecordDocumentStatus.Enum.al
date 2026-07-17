enum 70620 "GPI Record Document Status"
{
    Extensible = false;
    Caption = 'GPI Record Document Status';

    value(0; Pending) { Caption = 'Pending'; }
    value(1; Uploaded) { Caption = 'Uploaded'; }
    value(2; Failed) { Caption = 'Failed'; }
    value(3; Deleted) { Caption = 'Deleted'; }
}
