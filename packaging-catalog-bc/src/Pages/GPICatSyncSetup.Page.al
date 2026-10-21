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
        }
    }

    trigger OnOpenPage()
    begin
        Rec.GetSetup();
    end;
}
