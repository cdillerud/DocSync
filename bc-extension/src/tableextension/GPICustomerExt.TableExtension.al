tableextension 50102 "GPI Customer Ext" extends Customer
{
    fields
    {
        field(50100; "GPI Idempotency Key"; Code[100])
        {
            Caption = 'GPI Idempotency Key';
            DataClassification = CustomerContent;
        }
        field(50101; "GPI Source System"; Code[50])
        {
            Caption = 'GPI Source System';
            DataClassification = CustomerContent;
        }
        field(50102; "GPI Source Document ID"; Code[100])
        {
            Caption = 'GPI Source Document ID';
            DataClassification = CustomerContent;
        }
        field(50104; "GPI Created By Integration"; Code[50])
        {
            Caption = 'GPI Created By Integration';
            DataClassification = CustomerContent;
        }
        field(50105; "GPI Created DateTime"; DateTime)
        {
            Caption = 'GPI Created DateTime';
            DataClassification = CustomerContent;
        }
    }
}
