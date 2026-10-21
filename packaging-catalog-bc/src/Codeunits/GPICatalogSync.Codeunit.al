codeunit 71010 "GPI Catalog Sync"
{
    // Keeps the Packaging Catalog in step with the item list:
    //  - an item saved in a packaging item category with a description is added to the catalog, reading size,
    //    finish, finish type, color, material, style and packout from a description written the usual way
    //    ("16oz, 82-2040, CT, Flint, Glass, Salsa, Jar, FH"), with vendor and last direct cost from the item;
    //  - blocking or unblocking an item does the same to the catalog products linked to it.
    // Existing catalog values are never overwritten. Both behaviors are set on GPI Catalog Sync Setup;
    // adding items is off until someone turns it on. Nothing here can stop an item from being saved.

    [EventSubscriber(ObjectType::Table, Database::Item, 'OnAfterInsertEvent', '', false, false)]
    local procedure OnItemInserted(var Rec: Record Item; RunTrigger: Boolean)
    begin
        if not RunTrigger or Rec.IsTemporary() then
            exit;
        HandleItem(Rec);
    end;

    [EventSubscriber(ObjectType::Table, Database::Item, 'OnAfterModifyEvent', '', false, false)]
    local procedure OnItemModified(var Rec: Record Item; var xRec: Record Item; RunTrigger: Boolean)
    begin
        // Only edits people make (RunTrigger); cost adjustment and posting modify items without it.
        if not RunTrigger or Rec.IsTemporary() then
            exit;
        HandleItem(Rec);
    end;

    local procedure HandleItem(var Item: Record Item)
    var
        Setup: Record "GPI Cat Sync Setup";
    begin
        if not Setup.Get() then
            exit;
        if Setup."Mirror Item Blocked" then
            if MirrorBlocked(Item) > 0 then;
        if Setup."Auto Add New Items" then
            if AddItem(Item, Setup) then;
    end;

    procedure SyncAllItems(var Added: Integer; var BlockedChanged: Integer)
    var
        Setup: Record "GPI Cat Sync Setup";
        Item: Record Item;
    begin
        Setup.GetSetup();
        Added := 0;
        BlockedChanged := 0;
        Item.SetRange(Type, Item.Type::Inventory);
        if Item.FindSet() then
            repeat
                if AddItem(Item, Setup) then
                    Added += 1;
                BlockedChanged += MirrorBlocked(Item);
            until Item.Next() = 0;
        Setup."Last Sync Run" := CurrentDateTime();
        Setup."Last Sync Added" := Added;
        Setup."Last Sync Blocked" := BlockedChanged;
        Setup.Modify();
    end;

    procedure AddItem(var Item: Record Item; Setup: Record "GPI Cat Sync Setup"): Boolean
    var
        Product: Record "GPI Pack Product";
        Vendor: Record Vendor;
        Cost: Decimal;
    begin
        if not Qualifies(Item, Setup) then
            exit(false);
        Product.SetRange("BC Item No.", Item."No.");
        if not Product.IsEmpty() then
            exit(false);
        Product.Reset();
        if Product.Get(Item."No.") then
            exit(false);

        Product.Init();
        Product."No." := Item."No.";
        Product."BC Item No." := Item."No.";
        if (Item."Vendor No." <> '') and Vendor.Get(Item."Vendor No.") then
            Product."Vendor No." := Item."Vendor No.";
        if Item."Vendor Item No." <> '' then
            Product."Supplier Mold No." := CopyStr(Item."Vendor Item No.", 1, MaxStrLen(Product."Supplier Mold No."));
        ReadDescription(Item.Description, Product);
        Cost := ItemCost(Item);
        Product."Current Supplier Unit Cost" := Cost;
        Product."Price Effective Date" := Today();
        Product."Price Change Note" := CopyStr(StrSubstNo('Added automatically from BC item %1 (cost = last direct cost)', Format(Today(), 0, 9)), 1, MaxStrLen(Product."Price Change Note"));
        exit(Product.Insert(true));
    end;

    procedure Qualifies(var Item: Record Item; Setup: Record "GPI Cat Sync Setup"): Boolean
    var
        Upper: Text;
        Word: Text;
    begin
        // Something the sales team sources: an inventory item in a packaging category, with a description and a cost,
        // that isn't a fee, a charge or a quality/sample record.
        if Item.Type <> Item.Type::Inventory then
            exit(false);
        if Item.Blocked or (DelChr(Item.Description, '<>', ' ') = '') then
            exit(false);
        if not InCategories(Item."Item Category Code", Setup."Item Category Filter") then
            exit(false);
        if ItemCost(Item) = 0 then
            exit(false);
        Upper := ' ' + UpperCase(Item.Description) + ' ' + UpperCase(Item."No.") + ' ';
        foreach Word in NotProductWords() do
            if StrPos(Upper, Word) > 0 then
                exit(false);
        exit(true);
    end;

    local procedure NotProductWords(): List of [Text]
    var
        Words: List of [Text];
    begin
        Words.Add('CHARGE');
        Words.Add('SET UP');
        Words.Add('SETUP');
        Words.Add('FREIGHT');
        Words.Add('SURCHARGE');
        Words.Add(' FEE');
        Words.Add('TOOLING');
        Words.Add('DEPOSIT');
        Words.Add('QUALITY');
        Words.Add('SAMPLE');
        exit(Words);
    end;

    local procedure ItemCost(var Item: Record Item): Decimal
    begin
        if Item."Last Direct Cost" <> 0 then
            exit(Item."Last Direct Cost");
        exit(Item."Unit Cost");
    end;

    procedure RedoAutoAdded(var Removed: Integer; var Added: Integer; var BlockedChanged: Integer)
    var
        Product: Record "GPI Pack Product";
    begin
        // Removes the catalog products this sync added that nobody has edited since, then adds them again under the
        // current rules (categories, what counts as a product, how descriptions are read). Edited rows are kept.
        Removed := 0;
        Product.SetFilter("Price Change Note", 'Added automatically from BC item*');
        if Product.FindSet(true) then
            repeat
                if Product.SystemModifiedAt <= Product.SystemCreatedAt + 1000 then
                    if Product.Delete(true) then
                        Removed += 1;
            until Product.Next() = 0;
        SyncAllItems(Added, BlockedChanged);
    end;

    local procedure MirrorBlocked(var Item: Record Item): Integer
    var
        Product: Record "GPI Pack Product";
        Changed: Integer;
    begin
        Product.SetRange("BC Item No.", Item."No.");
        Product.SetFilter(Blocked, '<>%1', Item.Blocked);
        if Product.FindSet(true) then
            repeat
                Product.Blocked := Item.Blocked;
                if Product.Modify(true) then
                    Changed += 1;
            until Product.Next() = 0;
        exit(Changed);
    end;

    local procedure InCategories(Category: Code[20]; FilterText: Text): Boolean
    var
        Parts: List of [Text];
        Part: Text;
    begin
        if Category = '' then
            exit(false);
        Parts := UpperCase(FilterText).Split('|');
        foreach Part in Parts do
            if DelChr(Part, '<>', ' ') = Category then
                exit(true);
        exit(false);
    end;

    procedure ReadDescription(Description: Text; var Product: Record "GPI Pack Product")
    var
        Parts: List of [Text];
    begin
        // Gamer item descriptions are usually written in one order:
        //   size, finish, finish type, color, material, style..., category, packout
        //   e.g. "16oz, 82-2040, CT, Flint, Glass, Salsa, Jar, FH"
        // When the fifth part is a material, read by position (as the catalog was first filled); otherwise
        // recognize each part by what it looks like.
        Parts := Description.Split(',');
        if Parts.Count() >= 6 then
            if IsMaterial(UpperCase(DelChr(Parts.Get(5), '<>', ' '))) then begin
                ReadByPosition(Parts, Product);
                exit;
            end;
        ReadByKind(Description, Product);
    end;

    local procedure ReadByPosition(Parts: List of [Text]; var Product: Record "GPI Pack Product")
    var
        Token: Text;
        Upper: Text;
        StyleText: Text;
        CategoryWord: Text;
        i: Integer;
        StyleDone: Boolean;
    begin
        if TryCapacity(DelChr(Parts.Get(1), '<>', ' '), Product) then;
        Product.Finish := CopyStr(DelChr(Parts.Get(2), '<>', ' '), 1, MaxStrLen(Product.Finish));
        Product."Finish Type" := CopyStr(DelChr(Parts.Get(3), '<>', ' '), 1, MaxStrLen(Product."Finish Type"));
        Token := DelChr(Parts.Get(4), '<>', ' ');
        SetColor(Product, Token, UpperCase(Token));
        SetMaterial(Product, UpperCase(DelChr(Parts.Get(5), '<>', ' ')));
        for i := 6 to Parts.Count() do begin
            Token := DelChr(Parts.Get(i), '<>', ' ');
            Upper := UpperCase(Token);
            if Token <> '' then
                if IsPackout(Upper) then
                    AddPackout(Product, Token)
                else
                    if IsCategoryWord(Upper) then begin
                        StyleDone := true;
                        if CategoryWord = '' then
                            CategoryWord := Token;
                    end else
                        if not StyleDone then
                            if StyleText = '' then
                                StyleText := Token
                            else
                                StyleText += ' ' + Token;
        end;
        if StyleText = '' then
            StyleText := CategoryWord;
        Product.Style := CopyStr(StyleText, 1, MaxStrLen(Product.Style));
    end;

    local procedure ReadByKind(Description: Text; var Product: Record "GPI Pack Product")
    var
        Parts: List of [Text];
        Part: Text;
        Token: Text;
        Upper: Text;
        StyleText: Text;
        IsSize: Boolean;
        StyleDone: Boolean;
    begin
        // AL evaluates both sides of "and", so checks with side effects or indexing are nested, never combined.
        Parts := Description.Split(',');
        foreach Part in Parts do begin
            Token := DelChr(Part, '<>', ' ');
            Upper := UpperCase(Token);
            IsSize := false;
            if (Token <> '') and (Product.Capacity = 0) then
                IsSize := TryCapacity(Token, Product);
            if Token <> '' then
                if not IsSize then
                    if (Product.Finish = '') and IsFinish(Upper) then
                        Product.Finish := CopyStr(Token, 1, MaxStrLen(Product.Finish))
                    else
                        if (Product."Finish Type" = '') and IsFinishType(Upper) then
                            Product."Finish Type" := CopyStr(Token, 1, MaxStrLen(Product."Finish Type"))
                        else
                            if (Product.Color = '') and IsColor(Upper) then
                                SetColor(Product, Token, Upper)
                            else
                                if (Product.Material = '') and IsMaterial(Upper) then
                                    SetMaterial(Product, Upper)
                                else
                                    if IsPackout(Upper) then
                                        AddPackout(Product, Token)
                                    else
                                        if IsCategoryWord(Upper) then
                                            StyleDone := true
                                        else
                                            if not StyleDone and not IsNoiseWord(Upper) then
                                                AddStyle(StyleText, Token, MaxStrLen(Product.Style));
        end;
        Product.Style := CopyStr(StyleText, 1, MaxStrLen(Product.Style));
    end;

    local procedure IsNoiseWord(Upper: Text): Boolean
    begin
        // Liner, coating and compliance codes on can descriptions, not part of the style.
        exit(Upper in ['BPANI', 'PFASNI', 'RETORT', 'STD', 'PRINTED', 'DIGITALLY PRINTED', 'BRITE']);
    end;

    local procedure SetMaterial(var Product: Record "GPI Pack Product"; Upper: Text)
    begin
        if Upper in ['ALUM', 'ALUMINIUM'] then
            Upper := 'ALUMINUM';
        Product.Material := CopyStr(Upper, 1, MaxStrLen(Product.Material));
    end;

    local procedure SetColor(var Product: Record "GPI Pack Product"; Token: Text; Upper: Text)
    begin
        if Upper = 'CLEAR' then
            Product.Color := 'Flint'
        else
            Product.Color := CopyStr(Token, 1, MaxStrLen(Product.Color));
    end;

    local procedure AddPackout(var Product: Record "GPI Pack Product"; Token: Text)
    begin
        if Product.Packout = '' then
            Product.Packout := CopyStr(Token, 1, MaxStrLen(Product.Packout))
        else
            Product.Packout := CopyStr(Product.Packout + ' ' + Token, 1, MaxStrLen(Product.Packout));
    end;

    local procedure AddStyle(var StyleText: Text; Token: Text; MaxLength: Integer)
    begin
        if StyleText = '' then
            StyleText := Token
        else
            if StrLen(StyleText) + StrLen(Token) + 2 <= MaxLength then
                StyleText += ', ' + Token;
    end;

    local procedure TryCapacity(Token: Text; var Product: Record "GPI Pack Product"): Boolean
    var
        NumberText: Text;
        UnitText: Text;
        Value: Decimal;
        i: Integer;
    begin
        // "16oz", "0.5oz", "750ml", "1.75L", "128 oz"
        i := 0;
        repeat
            i += 1;
        until (i > StrLen(Token)) or not IsDigitOrDot(Token, i);
        if (i = 1) or (i > StrLen(Token)) then
            exit(false);
        NumberText := CopyStr(Token, 1, i - 1);
        UnitText := UpperCase(DelChr(CopyStr(Token, i), '<>', ' .'));
        if not (UnitText in ['OZ', 'ML', 'L', 'LTR', 'CC', 'GAL', 'GALLON', 'DRAM']) then
            exit(false);
        if not Evaluate(Value, NumberText, 9) then
            exit(false);
        Product.Capacity := Value;
        if UnitText = 'LTR' then
            UnitText := 'L';
        if UnitText = 'GALLON' then
            UnitText := 'GAL';
        Product."Capacity UOM" := CopyStr(UnitText, 1, MaxStrLen(Product."Capacity UOM"));
        exit(true);
    end;

    local procedure IsDigitOrDot(Value: Text; Position: Integer): Boolean
    begin
        if (Position < 1) or (Position > StrLen(Value)) then
            exit(false);
        exit(Value[Position] in ['0' .. '9', '.']);
    end;

    local procedure IsDigitAt(Value: Text; Position: Integer): Boolean
    begin
        if (Position < 1) or (Position > StrLen(Value)) then
            exit(false);
        exit(Value[Position] in ['0' .. '9']);
    end;

    local procedure EndsWith(Value: Text; Suffix: Text): Boolean
    begin
        if StrLen(Value) <= StrLen(Suffix) then
            exit(false);
        exit(CopyStr(Value, StrLen(Value) - StrLen(Suffix) + 1) = Suffix);
    end;

    local procedure IsFinish(Upper: Text): Boolean
    var
        Dash: Integer;
    begin
        // "82-2040", "38-400", "28-3500", "70G-450", "24MM", "18-605-405"; can diameters "202", "206"
        if not IsDigitAt(Upper, 1) then
            exit(false);
        if (StrLen(Upper) > 15) or (StrPos(Upper, ' ') > 0) then
            exit(false);
        if (StrLen(Upper) = 3) and (CopyStr(Upper, 1, 2) in ['20', '21']) and IsDigitAt(Upper, 3) then
            exit(true);
        if EndsWith(Upper, 'MM') then
            exit(true);
        Dash := StrPos(Upper, '-');
        if Dash < 2 then
            exit(false);
        exit(IsDigitAt(Upper, Dash + 1));
    end;

    local procedure IsFinishType(Upper: Text): Boolean
    begin
        exit(Upper in ['CT', 'LUG', 'ROPP', 'KERR', 'TE KERR', 'BARTOP', 'BAR TOP', 'CORK', 'CROWN', 'PRY', 'TE', 'CRC',
                       'BUTTRESS', 'TWIST', 'TWIST OFF', 'SNAP', 'PRESS', 'BEAD', 'PILFER PROOF']);
    end;

    local procedure IsColor(Upper: Text): Boolean
    begin
        exit(Upper in ['FLINT', 'CLEAR', 'AMBER', 'GREEN', 'EMERALD', 'COBALT', 'BLUE', 'WHITE', 'BLACK', 'NATURAL', 'GOLD',
                       'SILVER', 'RED', 'YELLOW', 'UVAG', 'ANTIQUE GREEN', 'GEORGIA GREEN', 'DEAD LEAF GREEN', 'BRITE',
                       'BLACK/WHITE', 'GOLD/WHITE', 'WHITE/WHITE', 'SILVER/WHITE']);
    end;

    local procedure IsMaterial(Upper: Text): Boolean
    begin
        exit(Upper in ['GLASS', 'PET', 'HDPE', 'LDPE', 'PP', 'PVC', 'ALUMINUM', 'ALUM', 'ALUMINIUM', 'TIN', 'TFS', 'METAL',
                       'PAPERBOARD', 'PLASTIC']);
    end;

    local procedure IsPackout(Upper: Text): Boolean
    begin
        if Upper in ['FH', 'HH', 'BULK', 'BULK FH', 'BULK HH'] then
            exit(true);
        if not IsDigitAt(Upper, 1) then
            exit(false);
        exit(EndsWith(Upper, 'PK'));
    end;

    local procedure IsCategoryWord(Upper: Text): Boolean
    begin
        exit(Upper in ['BOTTLE', 'JAR', 'CAP', 'CAN', 'END', 'CAN END', 'CROWN', 'TUBE', 'CLOSURE', 'LID', 'CARRIER', 'CARTON']);
    end;
}
