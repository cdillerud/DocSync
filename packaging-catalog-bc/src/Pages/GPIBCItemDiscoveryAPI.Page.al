page 71028 "GPI BC Item API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'catalogDiscovery';
    APIVersion = 'v1.0';
    Caption = 'bcItems';
    EntityName = 'bcItem';
    EntitySetName = 'bcItems';
    SourceTable = Item;
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
                field(id; Rec.SystemId)
                {
                    Caption = 'Id';
                    Editable = false;
                }
                field(itemNo; Rec."No.")
                {
                    Caption = 'Item No.';
                    Editable = false;
                }
                field(description; Rec.Description)
                {
                    Caption = 'Description';
                    Editable = false;
                }
                field(description2; Rec."Description 2")
                {
                    Caption = 'Description 2';
                    Editable = false;
                }
                field(itemType; Rec.Type)
                {
                    Caption = 'Item Type';
                    Editable = false;
                }
                field(baseUnitOfMeasure; Rec."Base Unit of Measure")
                {
                    Caption = 'Base Unit of Measure';
                    Editable = false;
                }
                field(itemCategoryCode; Rec."Item Category Code")
                {
                    Caption = 'Item Category Code';
                    Editable = false;
                }
                field(vendorNo; Rec."Vendor No.")
                {
                    Caption = 'Vendor No.';
                    Editable = false;
                }
                field(vendorItemNo; Rec."Vendor Item No.")
                {
                    Caption = 'Vendor Item No.';
                    Editable = false;
                }
                field(unitCost; Rec."Unit Cost")
                {
                    Caption = 'Unit Cost';
                    Editable = false;
                }
                field(lastDirectCost; Rec."Last Direct Cost")
                {
                    Caption = 'Last Direct Cost';
                    Editable = false;
                }
                field(grossWeight; Rec."Gross Weight")
                {
                    Caption = 'Gross Weight';
                    Editable = false;
                }
                field(netWeight; Rec."Net Weight")
                {
                    Caption = 'Net Weight';
                    Editable = false;
                }
                field(unitsPerParcel; Rec."Units per Parcel")
                {
                    Caption = 'Units per Parcel';
                    Editable = false;
                }
                field(unitVolume; Rec."Unit Volume")
                {
                    Caption = 'Unit Volume';
                    Editable = false;
                }
                field(manufacturerCode; Rec."Manufacturer Code")
                {
                    Caption = 'Manufacturer Code';
                    Editable = false;
                }
                field(countryRegionOriginCode; Rec."Country/Region of Origin Code")
                {
                    Caption = 'Country/Region of Origin Code';
                    Editable = false;
                }
                field(blocked; Rec.Blocked)
                {
                    Caption = 'Blocked';
                    Editable = false;
                }
                field(purchasingBlocked; Rec."Purchasing Blocked")
                {
                    Caption = 'Purchasing Blocked';
                    Editable = false;
                }
                field(salesBlocked; Rec."Sales Blocked")
                {
                    Caption = 'Sales Blocked';
                    Editable = false;
                }
                field(systemModifiedAt; Rec.SystemModifiedAt)
                {
                    Caption = 'System Modified At';
                    Editable = false;
                }
            }
        }
    }

    [ServiceEnabled]
    procedure refreshFieldMetadata(var ActionContext: WebServiceActionContext)
    var
        DiscoveryMgt: Codeunit "GPI Item Disc Mgt";
    begin
        DiscoveryMgt.RefreshItemFieldMetadata();
        SetActionResponse(ActionContext);
    end;

    [ServiceEnabled]
    procedure profileCustomFields(var ActionContext: WebServiceActionContext)
    var
        DiscoveryMgt: Codeunit "GPI Item Disc Mgt";
    begin
        DiscoveryMgt.ProfileLikelyCustomItemFields();
        SetActionResponse(ActionContext);
    end;

    local procedure SetActionResponse(var ActionContext: WebServiceActionContext)
    begin
        ActionContext.SetObjectType(ObjectType::Page);
        ActionContext.SetObjectId(Page::"GPI BC Item API");
        ActionContext.AddEntityKey(Rec.FieldNo(SystemId), Rec.SystemId);
        ActionContext.SetResultCode(WebServiceActionResultCode::Updated);
    end;
}
