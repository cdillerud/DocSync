page 71033 "GPI Cat Sync Setup"
{
    PageType = Card;
    SourceTable = "GPI Cat Sync Setup";
    ApplicationArea = All;
    UsageCategory = Administration;
    Caption = 'GPI Catalog Sync Setup';
    InsertAllowed = false;
    DeleteAllowed = false;

    layout
    {
        area(Content)
        {
            group(General)
            {
                Caption = 'Keep the catalog in step with items';
                field("Auto Add New Items"; Rec."Auto Add New Items")
                {
                    ApplicationArea = All;
                }
                field("Mirror Item Blocked"; Rec."Mirror Item Blocked")
                {
                    ApplicationArea = All;
                }
                field("Item Category Filter"; Rec."Item Category Filter")
                {
                    ApplicationArea = All;
                }
            }
            group(Reverse)
            {
                Caption = 'Create items from the catalog (optional)';
                field("Create Items from Catalog"; Rec."Create Items from Catalog")
                {
                    ApplicationArea = All;
                }
                field("Model Item No."; Rec."Model Item No.")
                {
                    ApplicationArea = All;
                }
            }
            group(LastRun)
            {
                Caption = 'Last full sync';
                field("Last Sync Run"; Rec."Last Sync Run")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies when Sync All Items last ran.';
                }
                field("Last Sync Added"; Rec."Last Sync Added")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies how many catalog products the last Sync All Items added.';
                }
                field("Last Sync Blocked"; Rec."Last Sync Blocked")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies how many catalog products the last Sync All Items blocked or unblocked.';
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(SyncAll)
            {
                ApplicationArea = All;
                Caption = 'Sync All Items';
                Image = Refresh;
                ToolTip = 'Adds every item in a packaging category that is missing from the Packaging Catalog, and blocks or unblocks catalog products to match their items. Existing catalog values are not changed.';

                trigger OnAction()
                var
                    Sync: Codeunit "GPI Catalog Sync";
                    Added: Integer;
                    BlockedChanged: Integer;
                begin
                    if not Confirm('Add every packaging item missing from the catalog and match blocked flags to the items?', false) then
                        exit;
                    Sync.SyncAllItems(Added, BlockedChanged);
                    CurrPage.Update(false);
                    Message('%1 products added to the catalog. %2 blocked flags matched to their items.', Added, BlockedChanged);
                end;
            }
            action(RedoAuto)
            {
                ApplicationArea = All;
                Caption = 'Redo Automatic Additions';
                Image = Restore;
                ToolTip = 'Removes the catalog products this sync added that nobody has edited since, and adds them again under the current settings. Use it after changing the categories. Edited products are kept.';

                trigger OnAction()
                var
                    Sync: Codeunit "GPI Catalog Sync";
                    Removed: Integer;
                    Added: Integer;
                    BlockedChanged: Integer;
                begin
                    if not Confirm('Remove the automatically added catalog products nobody has edited, and add them again under the current settings?', false) then
                        exit;
                    Sync.RedoAutoAdded(Removed, Added, BlockedChanged);
                    CurrPage.Update(false);
                    Message('%1 automatic additions removed, %2 products added under the current settings.', Removed, Added);
                end;
            }
            action(CreateItems)
            {
                ApplicationArea = All;
                Caption = 'Create Items for Catalog Products';
                Image = NewItem;
                ToolTip = 'Creates a BC item for every catalog product that has none and has a vendor, material, style and a size or finish, and links them. An item that already exists with the catalog number for the same vendor is linked instead. No cost is written to the items.';

                trigger OnAction()
                var
                    Product: Record "GPI Pack Product";
                    ItemCreate: Codeunit "GPI Cat Item Create";
                    Ready: Integer;
                    Created: Integer;
                    Linked: Integer;
                    Failed: Integer;
                    FirstError: Text;
                begin
                    Product.SetRange("BC Item No.", '');
                    Product.SetRange(Blocked, false);
                    if Product.FindSet() then
                        repeat
                            if ItemCreate.ReadyForItem(Product) then
                                Ready += 1;
                        until Product.Next() = 0;
                    if Ready = 0 then begin
                        Message('Every catalog product that is complete enough already has a BC item.');
                        exit;
                    end;
                    if not Confirm('%1 catalog products have no BC item. Create (or link) an item for each of them?', false, Ready) then
                        exit;
                    ItemCreate.CreateMissingItems(Created, Linked, Failed, FirstError);
                    if Failed = 0 then
                        Message('%1 items created and %2 existing items linked.', Created, Linked)
                    else
                        Message('%1 items created, %2 existing items linked, %3 not done. First problem: %4', Created, Linked, Failed, FirstError);
                end;
            }
            action(OpenCatalog)
            {
                ApplicationArea = All;
                Caption = 'Packaging Catalog';
                Image = List;
                RunObject = page "GPI Pack Products";
                ToolTip = 'Opens the Packaging Catalog.';
            }
        }
        area(Promoted)
        {
            actionref(SyncAll_Promoted; SyncAll)
            {
            }
            actionref(RedoAuto_Promoted; RedoAuto)
            {
            }
            actionref(CreateItems_Promoted; CreateItems)
            {
            }
        }
    }

    trigger OnOpenPage()
    begin
        Rec.GetSetup();
    end;
}
