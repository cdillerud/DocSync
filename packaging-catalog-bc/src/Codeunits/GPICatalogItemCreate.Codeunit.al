codeunit 71011 "GPI Cat Item Create"
{
    // The optional reverse sync: a Packaging Catalog product with no BC item gets one, and the two are linked.
    //  - Off until "Create Items for New Catalog Products" is turned on in GPI Catalog Sync Setup.
    //  - When on, a catalog product that is complete enough (vendor, material, style, and a size or finish) and has
    //    no BC item is picked up a few minutes after it is saved (a background task, so a catalog import or edit is
    //    never held up or failed by item creation, and edits made in those minutes are included).
    //  - The item number is the catalog product's number. If an item with that number already exists for the same
    //    vendor (or no vendor), it is linked instead; for another vendor, nothing is done.
    //  - Item category, base unit of measure and posting groups are copied from a similar item already in the
    //    catalog (same material and style, preferably the same vendor), or from the setup's model item.
    //  - The description is written the usual way ("16oz, 28-410, CT, Clear, PET, Bell Round, Bottle").
    //  - No cost is written to the item: catalog prices never go to the item card.
    TableNo = "GPI Pack Product";
    Permissions = tabledata Item = rim,
                  tabledata "Item Unit of Measure" = ri;

    trigger OnRun()
    begin
        CreateItem(Rec);
    end;

    [EventSubscriber(ObjectType::Table, Database::"GPI Pack Product", 'OnAfterInsertEvent', '', false, false)]
    local procedure OnProductInserted(var Rec: Record "GPI Pack Product"; RunTrigger: Boolean)
    begin
        if RunTrigger then
            Schedule(Rec);
    end;

    [EventSubscriber(ObjectType::Table, Database::"GPI Pack Product", 'OnAfterModifyEvent', '', false, false)]
    local procedure OnProductModified(var Rec: Record "GPI Pack Product"; var xRec: Record "GPI Pack Product"; RunTrigger: Boolean)
    begin
        if RunTrigger then
            Schedule(Rec);
    end;

    local procedure Schedule(var Product: Record "GPI Pack Product")
    var
        Setup: Record "GPI Cat Sync Setup";
    begin
        if Product.IsTemporary() then
            exit;
        if not Setup.Get() then
            exit;
        if not Setup."Create Items from Catalog" then
            exit;
        if not ReadyForItem(Product) then
            exit;
        if TaskScheduler.CanCreateTask() then
            TaskScheduler.CreateTask(Codeunit::"GPI Cat Item Create", 0, true, CompanyName(),
                CurrentDateTime() + 5 * 60 * 1000, Product.RecordId());
    end;

    procedure ReadyForItem(var Product: Record "GPI Pack Product"): Boolean
    begin
        if Product.Blocked or (Product."BC Item No." <> '') then
            exit(false);
        if (Product."Vendor No." = '') or (Product.Material = '') or (Product.Style = '') then
            exit(false);
        exit((Product.Capacity <> 0) or (Product.Finish <> ''));
    end;

    procedure CreateMissingItems(var Created: Integer; var Linked: Integer; var Failed: Integer; var FirstError: Text)
    var
        Product: Record "GPI Pack Product";
        Item: Record Item;
        Candidates: List of [Code[20]];
        ProductNo: Code[20];
        ItemExisted: Boolean;
    begin
        // The manual run (setup page action): every catalog product ready for an item, one at a time, each in its
        // own transaction so one failure doesn't stop the rest.
        Product.SetRange("BC Item No.", '');
        Product.SetRange(Blocked, false);
        if Product.FindSet() then
            repeat
                if ReadyForItem(Product) then
                    Candidates.Add(Product."No.");
            until Product.Next() = 0;
        foreach ProductNo in Candidates do begin
            Commit();
            Product.Get(ProductNo);
            ItemExisted := Item.Get(ProductNo);
            ClearLastError();
            if Codeunit.Run(Codeunit::"GPI Cat Item Create", Product) then begin
                Product.Get(ProductNo);
                if Product."BC Item No." <> '' then
                    if ItemExisted then
                        Linked += 1
                    else
                        Created += 1;
            end else begin
                Failed += 1;
                if FirstError = '' then
                    FirstError := StrSubstNo('%1: %2', ProductNo, GetLastErrorText());
            end;
        end;
    end;

    local procedure CreateItem(var Product: Record "GPI Pack Product")
    var
        Item: Record Item;
        Template: Record Item;
        Setup: Record "GPI Cat Sync Setup";
    begin
        if not Product.Get(Product."No.") then
            exit;
        if not ReadyForItem(Product) then
            exit;
        if Item.Get(Product."No.") then begin
            if (Item."Vendor No." <> '') and (Item."Vendor No." <> Product."Vendor No.") then
                Error('Item %1 already exists for vendor %2; link it by hand if it is the same product.', Item."No.", Item."Vendor No.");
            LinkProduct(Product, Item."No.");
            exit;
        end;
        if not FindTemplate(Product, Template) then begin
            if Setup.Get() then
                if Setup."Model Item No." <> '' then
                    if Template.Get(Setup."Model Item No.") then;
            if Template."No." = '' then
                Error('No similar item to copy the item category, unit of measure and posting groups from. Set a Model Item No. on GPI Catalog Sync Setup.');
        end;
        Template.TestField("Base Unit of Measure");

        Item.Init();
        Item."No." := Product."No.";
        Item.Insert(true);
        Item.Validate(Description, BuildDescription(Product, Template."Item Category Code"));
        Item.Type := Item.Type::Inventory;
        Item."Item Category Code" := Template."Item Category Code";
        Item."Gen. Prod. Posting Group" := Template."Gen. Prod. Posting Group";
        Item."VAT Prod. Posting Group" := Template."VAT Prod. Posting Group";
        Item."Inventory Posting Group" := Template."Inventory Posting Group";
        Item."Tax Group Code" := Template."Tax Group Code";
        Item."Costing Method" := Template."Costing Method";
        Item."Replenishment System" := Template."Replenishment System";
        Item.Validate("Base Unit of Measure", Template."Base Unit of Measure");
        Item."Purch. Unit of Measure" := Template."Base Unit of Measure";
        Item."Sales Unit of Measure" := Template."Base Unit of Measure";
        Item."Vendor No." := Product."Vendor No.";
        if Product."Supplier Mold No." <> '' then
            Item."Vendor Item No." := CopyStr(Product."Supplier Mold No.", 1, MaxStrLen(Item."Vendor Item No."));
        Item.Modify(true);
        LinkProduct(Product, Item."No.");
    end;

    local procedure LinkProduct(var Product: Record "GPI Pack Product"; ItemNo: Code[20])
    begin
        Product."BC Item No." := ItemNo;
        Product.Modify(true);
    end;

    local procedure FindTemplate(var Product: Record "GPI Pack Product"; var Template: Record Item): Boolean
    begin
        // Most alike first: same vendor, material and style; then same material and style; then same vendor and
        // material; then same material.
        if FindLike(Product, Template, true, true) then
            exit(true);
        if FindLike(Product, Template, false, true) then
            exit(true);
        if FindLike(Product, Template, true, false) then
            exit(true);
        exit(FindLike(Product, Template, false, false));
    end;

    local procedure FindLike(var Product: Record "GPI Pack Product"; var Template: Record Item; SameVendor: Boolean; SameStyle: Boolean): Boolean
    var
        Other: Record "GPI Pack Product";
    begin
        Other.SetFilter("BC Item No.", '<>%1', '');
        Other.SetFilter("No.", '<>%1', Product."No.");
        Other.SetRange(Material, Product.Material);
        if SameVendor then
            Other.SetRange("Vendor No.", Product."Vendor No.");
        if SameStyle then
            Other.SetRange(Style, Product.Style);
        if Other.FindSet() then
            repeat
                if Template.Get(Other."BC Item No.") then
                    if not Template.Blocked then
                        if (Template."Item Category Code" <> '') and (Template."Base Unit of Measure" <> '') then
                            exit(true);
            until Other.Next() = 0;
        Clear(Template);
        exit(false);
    end;

    procedure BuildDescription(var Product: Record "GPI Pack Product"; CategoryCode: Code[20]): Text[100]
    var
        Parts: List of [Text];
        Part: Text;
        Result: Text;
        CategoryWord: Text;
    begin
        // Gamer's usual order: size, finish, finish type, color, material, style, category, packout.
        if Product.Capacity <> 0 then
            Parts.Add(Format(Product.Capacity, 0, 9) + SizeUnit(Product."Capacity UOM"));
        AddPart(Parts, Product.Finish);
        AddPart(Parts, Product."Finish Type");
        AddPart(Parts, Product.Color);
        AddPart(Parts, Product.Material);
        AddPart(Parts, Product.Style);
        CategoryWord := CategoryText(CategoryCode);
        if CategoryWord <> '' then
            if StrPos(UpperCase(Product.Style), UpperCase(CategoryWord)) = 0 then
                Parts.Add(CategoryWord);
        if (Product.Packout <> '') and (StrPos(Product.Packout, ',') = 0) and (StrLen(Product.Packout) <= 15) then
            Parts.Add(Product.Packout);
        foreach Part in Parts do
            if Result = '' then
                Result := Part
            else
                Result += ', ' + Part;
        exit(CopyStr(Result, 1, 100));
    end;

    local procedure AddPart(var Parts: List of [Text]; Value: Text)
    begin
        Value := DelChr(Value, '<>', ' ');
        if Value <> '' then
            Parts.Add(Value);
    end;

    local procedure SizeUnit(Uom: Code[10]): Text
    begin
        case Uom of
            'OZ':
                exit('oz');
            'ML':
                exit('ml');
            'GAL':
                exit('gal');
            'CC':
                exit('cc');
        end;
        exit(Uom);
    end;

    local procedure CategoryText(CategoryCode: Code[20]): Text
    begin
        case CategoryCode of
            'BOTTLE':
                exit('Bottle');
            'JAR':
                exit('Jar');
            'CAP':
                exit('Cap');
            'CAN':
                exit('Can');
            'CANEND':
                exit('Can End');
            'CROWN':
                exit('Crown');
            'TUBE':
                exit('Tube');
            'CARRIER':
                exit('Carrier');
            'CARTON':
                exit('Carton');
        end;
        exit('');
    end;
}
