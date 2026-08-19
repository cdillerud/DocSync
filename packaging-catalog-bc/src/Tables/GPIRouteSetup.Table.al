table 71011 "GPI Route Setup"
{
    Caption = 'GPI Packaging Route Setup';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Primary Key"; Code[10])
        {
            Caption = 'Primary Key';
        }
        field(2; Enabled; Boolean)
        {
            Caption = 'Enable Route Service';
        }
        field(3; Provider; Enum "GPI Route Provider")
        {
            Caption = 'Route Provider';
        }
        field(4; Endpoint; Text[250])
        {
            Caption = 'Route Service Endpoint';
        }
        field(5; "Cache Days"; Integer)
        {
            Caption = 'Route Cache Days';
            MinValue = 1;
        }
    }

    keys
    {
        key(PK; "Primary Key")
        {
            Clustered = true;
        }
    }

    trigger OnInsert()
    begin
        if "Primary Key" = '' then
            "Primary Key" := 'SETUP';
        if Endpoint = '' then
            Endpoint := 'https://atlas.microsoft.com';
        if "Cache Days" <= 0 then
            "Cache Days" := 30;
        if Provider = "GPI Route Provider"::Manual then
            Provider := "GPI Route Provider"::"Azure Maps";
    end;
}
