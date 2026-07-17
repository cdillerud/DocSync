codeunit 70538 "GPI Extended Text Mgt."
{
    Permissions =
        tabledata "Extended Text Header" = r,
        tabledata "Extended Text Line" = r;

    procedure GetItemExtendedText(ItemNo: Code[20]): Text
    var
        ExtendedTextHeader: Record "Extended Text Header";
        ExtendedTextLine: Record "Extended Text Line";
        ResultBuilder: TextBuilder;
        HasText: Boolean;
    begin
        if ItemNo = '' then
            exit('');

        ExtendedTextHeader.SetRange("Table Name", ExtendedTextHeader."Table Name"::Item);
        ExtendedTextHeader.SetRange("No.", ItemNo);

        if ExtendedTextHeader.FindSet() then
            repeat
                if HeaderApplies(ExtendedTextHeader) then begin
                    ExtendedTextLine.Reset();
                    ExtendedTextLine.SetRange("Table Name", ExtendedTextHeader."Table Name");
                    ExtendedTextLine.SetRange("No.", ExtendedTextHeader."No.");
                    ExtendedTextLine.SetRange("Language Code", ExtendedTextHeader."Language Code");
                    ExtendedTextLine.SetRange("Text No.", ExtendedTextHeader."Text No.");
                    if ExtendedTextLine.FindSet() then
                        repeat
                            AppendExtendedTextLine(ResultBuilder, HasText, ExtendedTextLine.Text);
                        until ExtendedTextLine.Next() = 0;
                end;
            until ExtendedTextHeader.Next() = 0;

        exit(ResultBuilder.ToText());
    end;

    local procedure HeaderApplies(ExtendedTextHeader: Record "Extended Text Header"): Boolean
    begin
        if not ExtendedTextHeader."All Language Codes" and (ExtendedTextHeader."Language Code" <> '') then
            exit(false);

        if (ExtendedTextHeader."Starting Date" <> 0D) and (ExtendedTextHeader."Starting Date" > WorkDate()) then
            exit(false);

        if (ExtendedTextHeader."Ending Date" <> 0D) and (ExtendedTextHeader."Ending Date" < WorkDate()) then
            exit(false);

        exit(true);
    end;

    local procedure AppendExtendedTextLine(var ResultBuilder: TextBuilder; var HasText: Boolean; ExtendedTextValue: Text)
    begin
        ExtendedTextValue := DelChr(ExtendedTextValue, '<>', ' ');
        if ExtendedTextValue = '' then
            exit;

        if HasText then
            ResultBuilder.AppendLine('');

        ResultBuilder.Append(ExtendedTextValue);
        HasText := true;
    end;
}