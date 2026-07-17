codeunit 70521 "GPI Purchase Sent Status"
{
    Permissions =
        tabledata "Purchase Header" = rm;

    [EventSubscriber(ObjectType::Table, Database::"GPI Document Delivery Log", 'OnAfterModifyEvent', '', false, false)]
    local procedure DeliveryLogOnAfterModify(var Rec: Record "GPI Document Delivery Log"; var xRec: Record "GPI Document Delivery Log"; RunTrigger: Boolean)
    begin
        if Rec."Source Table ID" <> Database::"Purchase Header" then
            exit;

        if Rec.Status <> Rec.Status::Sent then
            exit;

        case Rec."Delivery Document Type" of
            Enum::"GPI Delivery Document Type"::"Purchase Order - Drop Ship",
            Enum::"GPI Delivery Document Type"::"Purchase Order - Warehouse":
                SetPurchaseHeaderBooleanField(Rec."Source Document No.", 50006, true);
            Enum::"GPI Delivery Document Type"::"Warehouse Receiving Notice":
                SetPurchaseHeaderBooleanField(Rec."Source Document No.", 50007, true);
        end;
    end;

    [EventSubscriber(ObjectType::Table, Database::"Purchase Header", 'OnBeforeModifyEvent', '', false, false)]
    local procedure PurchaseHeaderOnBeforeModify(var Rec: Record "Purchase Header"; var xRec: Record "Purchase Header"; RunTrigger: Boolean)
    var
        ExistingPurchaseHeader: Record "Purchase Header";
    begin
        if Rec."Document Type" <> Rec."Document Type"::Order then
            exit;

        if Rec.Status <> Rec.Status::Open then
            exit;

        if not ExistingPurchaseHeader.Get(Rec."Document Type", Rec."No.") then
            exit;

        if ExistingPurchaseHeader.Status = ExistingPurchaseHeader.Status::Open then
            exit;

        SetPurchaseHeaderBooleanFieldOnRecord(Rec, 50006, false);
    end;

    local procedure SetPurchaseHeaderBooleanField(PurchaseOrderNo: Code[20]; FieldNo: Integer; NewValue: Boolean)
    var
        PurchaseHeader: Record "Purchase Header";
        PurchaseHeaderRef: RecordRef;
        IndicatorField: FieldRef;
    begin
        if PurchaseOrderNo = '' then
            exit;

        if not PurchaseHeader.Get(PurchaseHeader."Document Type"::Order, PurchaseOrderNo) then
            exit;

        PurchaseHeaderRef.GetTable(PurchaseHeader);
        if not PurchaseHeaderRef.FieldExist(FieldNo) then
            exit;

        IndicatorField := PurchaseHeaderRef.Field(FieldNo);
        if Format(IndicatorField.Value) = Format(NewValue) then
            exit;

        IndicatorField.Value := NewValue;
        PurchaseHeaderRef.Modify(false);
    end;

    local procedure SetPurchaseHeaderBooleanFieldOnRecord(var PurchaseHeader: Record "Purchase Header"; FieldNo: Integer; NewValue: Boolean)
    var
        PurchaseHeaderRef: RecordRef;
        IndicatorField: FieldRef;
    begin
        PurchaseHeaderRef.GetTable(PurchaseHeader);
        if not PurchaseHeaderRef.FieldExist(FieldNo) then
            exit;

        IndicatorField := PurchaseHeaderRef.Field(FieldNo);
        IndicatorField.Value := NewValue;
        PurchaseHeaderRef.SetTable(PurchaseHeader);
    end;
}
