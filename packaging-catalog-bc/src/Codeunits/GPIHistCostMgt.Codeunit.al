codeunit 71100 "GPI Hist Cost Mgt"
{
    procedure BuildHistoricalEvidence(ItemNo: Code[20]; var TempBuffer: Record "GPI Hist Cost Buf" temporary)
    var
        ValueEntry: Record "Value Entry";
        ItemLedgerEntryNo: Integer;
    begin
        TempBuffer.Reset();
        TempBuffer.DeleteAll();

        if ItemNo = '' then
            exit;

        ValueEntry.SetRange("Item No.", ItemNo);
        ValueEntry.SetFilter("Item Charge No.", '<>%1', '');
        if not ValueEntry.FindSet() then
            exit;

        repeat
            ItemLedgerEntryNo := ValueEntry."Item Ledger Entry No.";
            if (ItemLedgerEntryNo <> 0) and not TempBuffer.Get(ItemLedgerEntryNo) then
                BuildGroup(ItemNo, ItemLedgerEntryNo, TempBuffer);
        until ValueEntry.Next() = 0;
    end;

    local procedure BuildGroup(ItemNo: Code[20]; ItemLedgerEntryNo: Integer; var TempBuffer: Record "GPI Hist Cost Buf" temporary)
    var
        ValueEntry: Record "Value Entry";
        ItemUOM: Record "Item Unit of Measure";
        QtyCandidate: Decimal;
        ChargeNo: Code[20];
    begin
        TempBuffer.Init();
        TempBuffer."Item Ledger Entry No." := ItemLedgerEntryNo;
        TempBuffer."Item No." := ItemNo;

        ValueEntry.SetRange("Item No.", ItemNo);
        ValueEntry.SetRange("Item Ledger Entry No.", ItemLedgerEntryNo);
        if ValueEntry.FindSet() then
            repeat
                if IsInboundEvidence(ValueEntry) then begin
                    if ValueEntry."Posting Date" > TempBuffer."Posting Date" then
                        TempBuffer."Posting Date" := ValueEntry."Posting Date";

                    QtyCandidate := 0;
                    if ValueEntry."Invoiced Quantity" > 0 then
                        QtyCandidate := Abs(ValueEntry."Invoiced Quantity")
                    else
                        if ValueEntry."Valued Quantity" > 0 then
                            QtyCandidate := Abs(ValueEntry."Valued Quantity");

                    if QtyCandidate > TempBuffer."Quantity EA" then
                        TempBuffer."Quantity EA" := QtyCandidate;

                    ChargeNo := ValueEntry."Item Charge No.";
                    if ChargeNo = '' then
                        TempBuffer."Direct Actual Cost" += ValueEntry."Cost Amount (Actual)"
                    else begin
                        case UpperCase(ChargeNo) of
                            'FREIGHT':
                                TempBuffer.Freight += ValueEntry."Cost Amount (Actual)";
                            'CUSTOMS':
                                TempBuffer.Customs += ValueEntry."Cost Amount (Actual)";
                            'DRAYAGE':
                                TempBuffer.Drayage += ValueEntry."Cost Amount (Actual)";
                            else
                                TempBuffer."Other Charges" += ValueEntry."Cost Amount (Actual)";
                        end;
                        AddChargeCode(TempBuffer."Charge Codes", ChargeNo);
                    end;
                end;
            until ValueEntry.Next() = 0;

        TempBuffer."Total Charges" :=
            TempBuffer.Freight +
            TempBuffer.Customs +
            TempBuffer.Drayage +
            TempBuffer."Other Charges";

        TempBuffer."Total Actual Cost" := TempBuffer."Direct Actual Cost" + TempBuffer."Total Charges";

        if TempBuffer."Quantity EA" > 0 then begin
            TempBuffer."Direct Cost per EA" := Round(TempBuffer."Direct Actual Cost" / TempBuffer."Quantity EA", 0.00001, '=');
            TempBuffer."Charges per EA" := Round(TempBuffer."Total Charges" / TempBuffer."Quantity EA", 0.00001, '=');
            TempBuffer."Landed Cost per EA" := Round(TempBuffer."Total Actual Cost" / TempBuffer."Quantity EA", 0.00001, '=');
        end;

        if ItemUOM.Get(ItemNo, 'M') then
            if ItemUOM."Qty. per Unit of Measure" > 0 then begin
                TempBuffer."M Qty. per UOM" := ItemUOM."Qty. per Unit of Measure";
                TempBuffer."Landed Cost per M" := Round(
                    TempBuffer."Landed Cost per EA" * TempBuffer."M Qty. per UOM",
                    0.00001,
                    '=');
            end;

        if TempBuffer."Total Charges" <> 0 then
            TempBuffer.Insert();
    end;

    local procedure IsInboundEvidence(ValueEntry: Record "Value Entry"): Boolean
    begin
        exit(
            (ValueEntry."Invoiced Quantity" > 0) or
            (ValueEntry."Valued Quantity" > 0) or
            (ValueEntry."Item Charge No." <> ''));
    end;

    local procedure AddChargeCode(var ChargeCodes: Text[250]; ChargeNo: Code[20])
    var
        NormalizedCodes: Text[250];
        NormalizedCharge: Text[20];
    begin
        if ChargeNo = '' then
            exit;

        NormalizedCodes := UpperCase(ChargeCodes);
        NormalizedCharge := UpperCase(ChargeNo);
        if StrPos(NormalizedCodes, NormalizedCharge) > 0 then
            exit;

        if ChargeCodes = '' then
            ChargeCodes := CopyStr(ChargeNo, 1, MaxStrLen(ChargeCodes))
        else
            ChargeCodes := CopyStr(ChargeCodes + ', ' + ChargeNo, 1, MaxStrLen(ChargeCodes));
    end;
}
