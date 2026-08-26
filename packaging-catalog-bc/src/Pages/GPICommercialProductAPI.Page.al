page 71126 "GPI Commercial Product API"
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
                field(vendorLocationCode; Rec."Vendor Location Code") { Caption = 'Vendor Location Code'; }
                field(transportMode; Rec."Transport Mode") { Caption = 'Transport Mode'; }
                field(fullLoadQuantity; Rec."Full Load Quantity") { Caption = 'Full Load Quantity'; }
                field(palletQuantity; Rec."Pallet Quantity") { Caption = 'Pallet Quantity'; }
                field(qtyPerLayer; Rec."Qty. per Layer") { Caption = 'Qty. per Layer'; }
                field(noOfLayers; Rec."No. of Layers") { Caption = 'No. of Layers'; }
                field(gramWeight; Rec."Gram Weight") { Caption = 'Gram Weight'; }
                field(currentSupplierUnitCost; Rec."Current Supplier Unit Cost") { Caption = 'Current Supplier Unit Cost'; }
                field(priceEffectiveDate; Rec."Price Effective Date") { Caption = 'Price Effective Date'; }
                field(blocked; Rec.Blocked) { Caption = 'Blocked'; }
            }
        }
    }
}
