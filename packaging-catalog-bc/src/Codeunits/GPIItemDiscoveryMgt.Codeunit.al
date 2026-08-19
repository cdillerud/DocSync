codeunit 71007 "GPI Item Disc Mgt"
{
    Permissions = tabledata "GPI Item Field Meta" = RIMD;

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
}
