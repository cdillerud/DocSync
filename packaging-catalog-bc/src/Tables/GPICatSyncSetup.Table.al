table 71015 "GPI Cat Sync Setup"
{
    Caption = 'GPI Catalog Sync Setup';
    DataClassification = SystemMetadata;
    LookupPageId = "GPI Cat Sync Setup";
    DrillDownPageId = "GPI Cat Sync Setup";

    fields
    {
        field(1; "Primary Key"; Code[10])
        {
            Caption = 'Primary Key';
        }
        field(10; "Auto Add New Items"; Boolean)
        {
            Caption = 'Add New Items to the Catalog';
            ToolTip = 'Specifies whether an item saved in a packaging item category is added to the Packaging Catalog automatically, with the size, finish, color and style read from its description. Off until someone turns it on.';
        }
        field(11; "Mirror Item Blocked"; Boolean)
        {
            Caption = 'Block Catalog Rows with Their Item';
            ToolTip = 'Specifies whether blocking or unblocking an item does the same to the catalog products linked to it.';
            InitValue = true;
        }
        field(12; "Item Category Filter"; Text[250])
        {
            Caption = 'Packaging Item Categories';
            ToolTip = 'Specifies the item categories that belong in the Packaging Catalog, separated by |. Items in other categories, such as PALLET and OTHER, are never added. Fees, charges, quality and sample items and items with no cost are never added either.';
            InitValue = 'BOTTLE|JAR|CAP|CAN|CANEND|CROWN|TUBE|CARRIER|CARTON|FLEX';
        }
        field(20; "Last Sync Run"; DateTime)
        {
            Caption = 'Last Sync Run';
            Editable = false;
        }
        field(21; "Last Sync Added"; Integer)
        {
            Caption = 'Products Added in Last Sync';
            Editable = false;
        }
        field(22; "Last Sync Blocked"; Integer)
        {
            Caption = 'Blocked Changes in Last Sync';
            Editable = false;
        }
    }

    keys
    {
        key(PK; "Primary Key")
        {
            Clustered = true;
        }
    }

    procedure GetSetup(): Boolean
    begin
        if Get() then
            exit(true);
        Init();
        exit(Insert());
    end;
}
