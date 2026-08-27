table 50190 "GPI Hub Setup"
{
    Caption = 'GPI Hub Setup';
    DataClassification = SystemMetadata;

    fields
    {
        field(1; "Primary Key"; Code[10])
        {
            Caption = 'Primary Key';
            DataClassification = SystemMetadata;
        }
        field(2; "Hub Base URL"; Text[250])
        {
            Caption = 'Hub Base URL';
            DataClassification = SystemMetadata;

            trigger OnValidate()
            var
                NormalizedUrl: Text;
            begin
                NormalizedUrl := DelChr("Hub Base URL", '>', '/');

                if NormalizedUrl = '' then begin
                    "Hub Base URL" := '';
                    exit;
                end;

                if LowerCase(CopyStr(NormalizedUrl, 1, 8)) <> 'https://' then
                    Error('GPI Hub Base URL must use HTTPS. HTTP endpoints are not allowed.');

                "Hub Base URL" := CopyStr(NormalizedUrl, 1, MaxStrLen("Hub Base URL"));
            end;
        }
        field(3; "Hub API Key"; Text[250])
        {
            Caption = 'Hub API Key';
            DataClassification = SystemMetadata;
            ExtendedDatatype = Masked;
        }
    }

    keys
    {
        key(PK; "Primary Key")
        {
            Clustered = true;
        }
    }
}
