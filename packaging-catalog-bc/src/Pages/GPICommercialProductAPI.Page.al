page 71126 "GPI Comm Product API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialAgents';
    APIVersion = 'v1.0';
    Caption = 'commercialProducts';
    EntityName = 'commercialProduct';
    EntitySetName = 'commercialProducts';
    SourceTable = "GPI Pack Product";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId) { Caption = 'Id'; }
                field(productNo; Rec."No.") { Caption = 'Product No.'; }
                field(bcItemNo; Rec."BC Item No.") { Caption = 'BC Item No.'; }
                field(bcItemDescription; Rec."BC Item Description") { Caption = 'BC Item Description'; }
                field(bcItemCategory; Rec."BC Item Category") { Caption = 'BC Item Category'; }
                field(bcBaseUom; Rec."BC Base UOM") { Caption = 'BC Base UOM'; }
                field(bcItemBlocked; Rec."BC Item Blocked") { Caption = 'BC Item Blocked'; }
                field(supplierMoldNo; Rec."Supplier Mold No.") { Caption = 'Supplier Mold No.'; }
                field(material; Rec.Material) { Caption = 'Material'; }
                field(capacity; Rec.Capacity) { Caption = 'Capacity'; }
                field(capacityUom; Rec."Capacity UOM") { Caption = 'Capacity UOM'; }
                field(finish; Rec.Finish) { Caption = 'Finish'; }
                field(finishType; Rec."Finish Type") { Caption = 'Finish Type'; }
                field(color; Rec.Color) { Caption = 'Color'; }
                field(style; Rec.Style) { Caption = 'Style'; }
                field(packout; Rec.Packout) { Caption = 'Packout'; }
                field(packoutType; Rec."Packout Type") { Caption = 'Packout Type'; }
                field(vendorNo; Rec."Vendor No.") { Caption = 'Vendor No.'; }
                field(vendorName; Rec."Vendor Name") { Caption = 'Vendor Name'; }
                field(vendorLocationCode; Rec."Vendor Location Code") { Caption = 'Vendor Location Code'; }
                field(fobCity; Rec."FOB City") { Caption = 'FOB City'; }
                field(fobStateProvince; Rec."FOB State/Province") { Caption = 'FOB State/Province'; }
                field(transportMode; Rec."Transport Mode") { Caption = 'Transport Mode'; }
                field(fullLoadQuantity; Rec."Full Load Quantity") { Caption = 'Full Load Quantity'; }
                field(noOfPallets; Rec."No. of Pallets") { Caption = 'No. of Pallets'; }
                field(palletQuantity; Rec."Pallet Quantity") { Caption = 'Pallet Quantity'; }
                field(qtyPerLayer; Rec."Qty. per Layer") { Caption = 'Qty. per Layer'; }
                field(noOfLayers; Rec."No. of Layers") { Caption = 'No. of Layers'; }
                field(gramWeight; Rec."Gram Weight") { Caption = 'Gram Weight'; }
                field(currentSupplierUnitCost; Rec."Current Supplier Unit Cost") { Caption = 'Current Supplier Unit Cost'; }
                field(metricTonCost; Rec."Metric Ton Cost") { Caption = 'Metric Ton Cost'; }
                field(priceEffectiveDate; Rec."Price Effective Date") { Caption = 'Price Effective Date'; }
                field(priceChangeNote; Rec."Price Change Note") { Caption = 'Price Change Note'; }
                field(drawingFileName; Rec."Drawing File Name") { Caption = 'Drawing File Name'; }
                field(blocked; Rec.Blocked) { Caption = 'Blocked'; }
            }
        }
    }

    trigger OnAfterGetRecord()
    begin
        Rec.CalcFields(
            "BC Item Description",
            "BC Item Category",
            "BC Base UOM",
            "BC Item Blocked",
            "Vendor Name",
            "FOB City",
            "FOB State/Province");
    end;
}
