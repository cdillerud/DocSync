page 71021 "GPI Comp Line API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'packagingComparisons';
    APIVersion = 'v1.0';
    Caption = 'packagingComparisonLines';
    EntityName = 'packagingComparisonLine';
    EntitySetName = 'packagingComparisonLines';
    SourceTable = "GPI Pack Comp Line";
    ODataKeyFields = SystemId;
    InsertAllowed = true;
    ModifyAllowed = true;
    DeleteAllowed = true;
    DelayedInsert = true;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'Id';
                    Editable = false;
                }
                field(compareEntryNo; Rec."Compare Entry No.")
                {
                    Caption = 'Comparison No.';
                }
                field(lineNo; Rec."Line No.")
                {
                    Caption = 'Line No.';
                    Editable = false;
                }
                field(productNo; Rec."Product No.")
                {
                    Caption = 'Gamer ID';
                }
                field(bcItemNo; Rec."BC Item No.")
                {
                    Caption = 'BC Item No.';
                    Editable = false;
                }
                field(vendorNo; Rec."Vendor No.")
                {
                    Caption = 'Vendor No.';
                    Editable = false;
                }
                field(vendorName; Rec."Vendor Name")
                {
                    Caption = 'Vendor Name';
                    Editable = false;
                }
                field(vendorLocationCode; Rec."Vendor Location Code")
                {
                    Caption = 'Vendor FOB Location';
                    Editable = false;
                }
                field(fobCity; Rec."FOB City")
                {
                    Caption = 'FOB City';
                    Editable = false;
                }
                field(fobStateProvince; Rec."FOB State/Province")
                {
                    Caption = 'FOB State/Province';
                    Editable = false;
                }
                field(mode; Rec.Mode)
                {
                    Caption = 'Transport Mode';
                    Editable = false;
                }
                field(quantity; Rec.Quantity)
                {
                    Caption = 'Comparison Quantity';
                }
                field(gramWeight; Rec."Gram Weight")
                {
                    Caption = 'Gram Weight';
                    Editable = false;
                }
                field(noOfPallets; Rec."No. of Pallets")
                {
                    Caption = 'No. of Pallets';
                }
                field(supplierUnitCost; Rec."Supplier Unit Cost")
                {
                    Caption = 'Supplier Unit Cost';
                    Editable = false;
                }
                field(palletCostPerPallet; Rec."Pallet Cost per Pallet")
                {
                    Caption = 'Pallet Cost per Pallet';
                }
                field(tariffPct; Rec."Tariff %")
                {
                    Caption = 'Tariff %';
                }
                field(internationalFreightTotal; Rec."Intl Freight Total")
                {
                    Caption = 'International Freight Total';
                }
                field(customsTotal; Rec."Customs Total")
                {
                    Caption = 'Customs Total';
                }
                field(deliveryTotal; Rec."Delivery Total")
                {
                    Caption = 'Delivery Charge Total';
                }
                field(shipmentCwt; Rec."Shipment CWT")
                {
                    Caption = 'Shipment CWT';
                    Editable = false;
                }
                field(freightRateEntryNo; Rec."Freight Rate Entry No.")
                {
                    Caption = 'Freight Rate Entry No.';
                    Editable = false;
                }
                field(ratePerCwt; Rec."Rate per CWT")
                {
                    Caption = 'Rate per CWT';
                    Editable = false;
                }
                field(minimumCharge; Rec."Minimum Charge")
                {
                    Caption = 'Minimum Charge';
                    Editable = false;
                }
                field(fuelSurchargePct; Rec."Fuel Surcharge %")
                {
                    Caption = 'Fuel Surcharge %';
                    Editable = false;
                }
                field(domesticFreightTotal; Rec."Domestic Freight Total")
                {
                    Caption = 'Domestic Freight Total';
                    Editable = false;
                }
                field(domesticFreightPerUnit; Rec."Domestic Frt per Unit")
                {
                    Caption = 'Domestic Freight per Unit';
                    Editable = false;
                }
                field(palletCostPerUnit; Rec."Pallet Cost per Unit")
                {
                    Caption = 'Pallet Cost per Unit';
                    Editable = false;
                }
                field(tariffPerUnit; Rec."Tariff per Unit")
                {
                    Caption = 'Tariff per Unit';
                    Editable = false;
                }
                field(internationalFreightPerUnit; Rec."Intl Freight per Unit")
                {
                    Caption = 'International Freight per Unit';
                    Editable = false;
                }
                field(customsPerUnit; Rec."Customs per Unit")
                {
                    Caption = 'Customs per Unit';
                    Editable = false;
                }
                field(deliveryPerUnit; Rec."Delivery per Unit")
                {
                    Caption = 'Delivery per Unit';
                    Editable = false;
                }
                field(landedCostPerUnit; Rec."Landed Cost per Unit")
                {
                    Caption = 'Landed Cost per Unit';
                    Editable = false;
                }
                field(suggestedSellPrice; Rec."Suggested Sell Price")
                {
                    Caption = 'Suggested Sell Price per Unit';
                    Editable = false;
                }
                field(rank; Rec.Rank)
                {
                    Caption = 'Rank';
                    Editable = false;
                }
                field(costAboveBest; Rec."Cost Above Best")
                {
                    Caption = 'Cost Above Best per Unit';
                    Editable = false;
                }
                field(isComplete; Rec."Is Complete")
                {
                    Caption = 'Rankable';
                    Editable = false;
                }
                field(incompleteReason; Rec."Incomplete Reason")
                {
                    Caption = 'Incomplete Reason';
                    Editable = false;
                }
                field(calculatedAt; Rec."Calculated At")
                {
                    Caption = 'Calculated At';
                    Editable = false;
                }
            }
        }
    }
}
