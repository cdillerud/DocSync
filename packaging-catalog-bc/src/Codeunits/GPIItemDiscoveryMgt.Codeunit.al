codeunit 71007 "GPI Item Disc Mgt"
{
    Permissions =
        tabledata "GPI Item Field Meta" = RIMD,
        tabledata "GPI Item Field Stat" = RIMD;

    procedure RefreshItemFieldMetadata(): Integer
    var
        FieldMetadata: Record Field;
        ItemFieldMeta: Record "GPI Item Field Meta";
        ScanTimestamp: DateTime;
        FieldCount: Integer;
    begin
        ScanTimestamp := CurrentDateTime();
        ItemFieldMeta.DeleteAll(false);

        FieldMetadata.SetRange(TableNo, Database::Item);
        if FieldMetadata.FindSet() then
            repeat
                ItemFieldMeta.Init();
                ItemFieldMeta."Field No." := FieldMetadata."No.";
                ItemFieldMeta."Field Name" := CopyStr(FieldMetadata.FieldName, 1, MaxStrLen(ItemFieldMeta."Field Name"));
                ItemFieldMeta."Field Caption" := CopyStr(FieldMetadata."Field Caption", 1, MaxStrLen(ItemFieldMeta."Field Caption"));
                ItemFieldMeta."Data Type" := CopyStr(Format(FieldMetadata.Type), 1, MaxStrLen(ItemFieldMeta."Data Type"));
                ItemFieldMeta.Length := FieldMetadata.Len;
                ItemFieldMeta."Field Class" := CopyStr(Format(FieldMetadata.Class), 1, MaxStrLen(ItemFieldMeta."Field Class"));
                ItemFieldMeta.Enabled := FieldMetadata.Enabled;
                ItemFieldMeta."Type Name" := CopyStr(FieldMetadata."Type Name", 1, MaxStrLen(ItemFieldMeta."Type Name"));
                ItemFieldMeta."External Name" := CopyStr(FieldMetadata.ExternalName, 1, MaxStrLen(ItemFieldMeta."External Name"));
                ItemFieldMeta."Relation Table No." := FieldMetadata.RelationTableNo;
                ItemFieldMeta."Relation Field No." := FieldMetadata.RelationFieldNo;
                ItemFieldMeta."Scanned At" := ScanTimestamp;
                ItemFieldMeta.Insert(false);
                FieldCount += 1;
            until FieldMetadata.Next() = 0;

        exit(FieldCount);
    end;

    procedure ProfileLikelyCustomItemFields(): Integer
    var
        Item: Record Item;
        ItemFieldMeta: Record "GPI Item Field Meta";
        ItemFieldStat: Record "GPI Item Field Stat";
        ItemRef: RecordRef;
        ItemNoFieldRef: FieldRef;
        ValueFieldRef: FieldRef;
        ScanTimestamp: DateTime;
        ValueText: Text;
        SampleValues: Text;
        SampleItemNos: Text;
        MatchedKeyword: Text[30];
        TotalItemCount: Integer;
        NondefaultCount: Integer;
        SampleCount: Integer;
        ProfiledFieldCount: Integer;
    begin
        if ItemFieldMeta.IsEmpty() then
            RefreshItemFieldMetadata();

        ScanTimestamp := CurrentDateTime();
        TotalItemCount := Item.Count();
        ItemFieldStat.DeleteAll(false);

        ItemFieldMeta.SetRange(Enabled, true);
        ItemFieldMeta.SetRange("Field Class", 'Normal');
        ItemFieldMeta.SetFilter("Field No.", '50000..1999999999');
        if not ItemFieldMeta.FindSet() then
            exit(0);

        repeat
            NondefaultCount := 0;
            SampleCount := 0;
            SampleValues := '';
            SampleItemNos := '';
            MatchedKeyword := '';

            ItemRef.Open(Database::Item);
            ValueFieldRef := ItemRef.Field(ItemFieldMeta."Field No.");
            ItemNoFieldRef := ItemRef.Field(Item.FieldNo("No."));

            if ItemRef.FindSet() then
                repeat
                    ValueText := Format(ValueFieldRef.Value());
                    if HasMeaningfulValue(ItemFieldMeta."Data Type", ValueText) then begin
                        NondefaultCount += 1;
                        if SampleCount < 8 then begin
                            AppendSample(SampleValues, ValueText, 2048);
                            AppendSample(SampleItemNos, Format(ItemNoFieldRef.Value()), 500);
                            SampleCount += 1;
                        end;
                    end;
                until ItemRef.Next() = 0;

            ItemRef.Close();

            ItemFieldStat.Init();
            ItemFieldStat."Field No." := ItemFieldMeta."Field No.";
            ItemFieldStat."Field Name" := ItemFieldMeta."Field Name";
            ItemFieldStat."Field Caption" := ItemFieldMeta."Field Caption";
            ItemFieldStat."Data Type" := ItemFieldMeta."Data Type";
            ItemFieldStat."Total Item Count" := TotalItemCount;
            ItemFieldStat."Nondefault Count" := NondefaultCount;
            if TotalItemCount > 0 then
                ItemFieldStat."Nondefault Percent" := Round((NondefaultCount / TotalItemCount) * 100, 0.01, '=');
            ItemFieldStat."Sample Values" := CopyStr(SampleValues, 1, MaxStrLen(ItemFieldStat."Sample Values"));
            ItemFieldStat."Sample Item Nos." := CopyStr(SampleItemNos, 1, MaxStrLen(ItemFieldStat."Sample Item Nos."));
            ItemFieldStat."Packaging Relevant" := FindPackagingKeyword(ItemFieldMeta."Field Name", ItemFieldMeta."Field Caption", MatchedKeyword);
            ItemFieldStat."Matched Keyword" := MatchedKeyword;
            ItemFieldStat."Scanned At" := ScanTimestamp;
            ItemFieldStat.Insert(false);
            ProfiledFieldCount += 1;
        until ItemFieldMeta.Next() = 0;

        exit(ProfiledFieldCount);
    end;

    local procedure HasMeaningfulValue(DataTypeText: Text; ValueText: Text): Boolean
    var
        NumericValue: Decimal;
        BooleanValue: Boolean;
        TypeText: Text;
    begin
        ValueText := DelChr(ValueText, '<>', ' ');
        if ValueText = '' then
            exit(false);

        TypeText := UpperCase(DataTypeText);
        case TypeText of
            'DECIMAL', 'INTEGER', 'BIGINTEGER', 'DURATION':
                begin
                    if Evaluate(NumericValue, ValueText) then
                        exit(NumericValue <> 0);
                    exit(true);
                end;
            'BOOLEAN':
                begin
                    if Evaluate(BooleanValue, ValueText) then
                        exit(BooleanValue);
                    exit(true);
                end;
        end;

        exit(true);
    end;

    local procedure AppendSample(var TargetText: Text; NewValue: Text; MaxLength: Integer)
    begin
        if TargetText <> '' then
            TargetText += ' | ';
        TargetText += NewValue;
        TargetText := CopyStr(TargetText, 1, MaxLength);
    end;

    local procedure FindPackagingKeyword(FieldName: Text; FieldCaption: Text; var MatchedKeyword: Text[30]): Boolean
    var
        Keywords: List of [Text];
        Keyword: Text;
        SearchText: Text;
    begin
        SearchText := UpperCase(FieldName + ' ' + FieldCaption);
        Keywords.Add('MATERIAL');
        Keywords.Add('CAPACITY');
        Keywords.Add('FINISH');
        Keywords.Add('COLOR');
        Keywords.Add('STYLE');
        Keywords.Add('PACK');
        Keywords.Add('PALLET');
        Keywords.Add('LAYER');
        Keywords.Add('GRAM');
        Keywords.Add('WEIGHT');
        Keywords.Add('MOLD');
        Keywords.Add('MOULD');
        Keywords.Add('FOB');
        Keywords.Add('LOAD');
        Keywords.Add('CASE');
        Keywords.Add('CARTON');
        Keywords.Add('DIMENSION');
        Keywords.Add('HEIGHT');
        Keywords.Add('WIDTH');
        Keywords.Add('DIAMETER');
        Keywords.Add('VOLUME');
        Keywords.Add('SUPPLIER');
        Keywords.Add('DRAWING');
        Keywords.Add('IMAGE');

        foreach Keyword in Keywords do
            if StrPos(SearchText, Keyword) > 0 then begin
                MatchedKeyword := CopyStr(Keyword, 1, MaxStrLen(MatchedKeyword));
                exit(true);
            end;

        exit(false);
    end;
}
