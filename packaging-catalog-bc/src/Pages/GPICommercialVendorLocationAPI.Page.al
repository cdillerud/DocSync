page 71131 "GPI Comm VLoc API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialAgents';
    APIVersion = 'v1.0';
    Caption = 'commercialVendorLocations';
    EntityName = 'commercialVendorLocation';
    EntitySetName = 'commercialVendorLocations';
    SourceTable = "GPI Pack Vendor Loc";
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
                field(vendorNo; Rec."Vendor No.") { Caption = 'Vendor No.'; }
                field(locationCode; Rec.Code) { Caption = 'Location Code'; }
                field(description; Rec.Description) { Caption = 'Description'; }
                field(address; Rec.Address) { Caption = 'Address'; }
                field(address2; Rec."Address 2") { Caption = 'Address 2'; }
                field(city; Rec.City) { Caption = 'City'; }
                field(stateProvince; Rec."State/Province") { Caption = 'State/Province'; }
                field(postCode; Rec."Post Code") { Caption = 'Post Code'; }
                field(countryRegionCode; Rec."Country/Region Code") { Caption = 'Country/Region Code'; }
                field(latitude; Rec.Latitude) { Caption = 'Latitude'; }
                field(longitude; Rec.Longitude) { Caption = 'Longitude'; }
                field(defaultFob; Rec."Default FOB") { Caption = 'Default FOB'; }
                field(blocked; Rec.Blocked) { Caption = 'Blocked'; }
            }
        }
    }
}
