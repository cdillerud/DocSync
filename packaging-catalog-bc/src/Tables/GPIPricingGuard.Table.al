table 71005 "GPI Pricing Guard"
{
    Caption = 'GPI Pricing Guardrail';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; Enabled; Boolean)
        {
            Caption = 'Enabled';
            InitValue = true;
        }
        field(3; "Customer No."; Code[20])
        {
            Caption = 'Customer No. (blank = all)';

            trigger OnValidate()
            var
                Customer: Record Customer;
            begin
                if "Customer No." <> '' then
                    Customer.Get("Customer No.");
            end;
        }
        field(4; "Item No."; Code[20])
        {
            Caption = 'Item No. (blank = all)';

            trigger OnValidate()
            var
                Item: Record Item;
            begin
                if "Item No." <> '' then
                    Item.Get("Item No.");
            end;
        }
        field(5; "Rule Type"; Enum "GPI Price Rule Type")
        {
            Caption = 'Rule Type';
        }
        field(6; "Locked Sell Price"; Decimal)
        {
            Caption = 'Locked Sell Price';
            DecimalPlaces = 0 : 5;
        }
        field(7; "Effective From"; Date)
        {
            Caption = 'Effective From';
        }
        field(8; "Effective To"; Date)
        {
            Caption = 'Effective To';
        }
        field(9; Approver; Text[100])
        {
            Caption = 'Approver';
        }
        field(10; Notes; Text[250])
        {
            Caption = 'Notes';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(CustomerItem; "Customer No.", "Item No.", Enabled)
        {
        }
    }

    trigger OnInsert()
    begin
        ValidateRule();
    end;

    trigger OnModify()
    begin
        ValidateRule();
    end;

    local procedure ValidateRule()
    begin
        if ("Effective From" <> 0D) and ("Effective To" <> 0D) and ("Effective To" < "Effective From") then
            Error('Effective To cannot be before Effective From.');

        if ("Rule Type" = "GPI Price Rule Type"::"Fixed Price") and ("Locked Sell Price" <= 0) then
            Error('Locked Sell Price must be greater than zero for a Fixed Price rule.');
    end;
}
