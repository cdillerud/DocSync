table 71104 "GPI Spiro Cust Map"
{
    Caption = 'GPI Spiro Customer Mapping';
    DataClassification = CustomerContent;
    LookupPageId = "GPI Spiro Cust Maps";
    DrillDownPageId = "GPI Spiro Cust Maps";

    fields
    {
        field(1; "BC Customer No."; Code[20])
        {
            Caption = 'BC Customer No.';
            TableRelation = Customer."No.";

            trigger OnValidate()
            var
                Customer: Record Customer;
            begin
                Clear("BC Customer SystemId");
                if Customer.Get("BC Customer No.") then
                    "BC Customer SystemId" := Customer.SystemId;
            end;
        }
        field(2; "BC Customer SystemId"; Guid)
        {
            Caption = 'BC Customer SystemId';
            Editable = false;
        }
        field(3; "BC Customer Name"; Text[100])
        {
            Caption = 'BC Customer Name';
            FieldClass = FlowField;
            CalcFormula = lookup(Customer.Name where("No." = field("BC Customer No.")));
            Editable = false;
        }
        field(4; "Spiro Company ID"; Text[100])
        {
            Caption = 'Spiro Company ID';
        }
        field(5; "Spiro Company Name"; Text[100])
        {
            Caption = 'Spiro Company Name';
        }
        field(6; "Spiro Company URL"; Text[250])
        {
            Caption = 'Spiro Company URL';
        }
        field(7; "Last Synced At"; DateTime)
        {
            Caption = 'Last Synced At';
        }
        field(8; "Last Synced By"; Text[100])
        {
            Caption = 'Last Synced By';
        }
    }

    keys
    {
        key(PK; "BC Customer No.")
        {
            Clustered = true;
        }
        key(SpiroCompany; "Spiro Company ID")
        {
        }
    }

    trigger OnInsert()
    begin
        StampSyncMetadata();
    end;

    trigger OnModify()
    begin
        StampSyncMetadata();
    end;

    local procedure StampSyncMetadata()
    begin
        "Last Synced At" := CurrentDateTime();
        "Last Synced By" := CopyStr(UserId(), 1, MaxStrLen("Last Synced By"));
    end;
}
