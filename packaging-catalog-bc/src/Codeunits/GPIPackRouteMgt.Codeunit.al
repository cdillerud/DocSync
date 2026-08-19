codeunit 71006 "GPI Pack Route Mgt"
{
    procedure EnsureSetup(var Setup: Record "GPI Route Setup")
    begin
        if Setup.Get('SETUP') then
            exit;

        Setup.Init();
        Setup."Primary Key" := 'SETUP';
        Setup.Enabled := false;
        Setup.Provider := "GPI Route Provider"::"Azure Maps";
        Setup.Endpoint := 'https://atlas.microsoft.com';
        Setup."Cache Days" := 30;
        Setup.Insert(true);
    end;

    procedure SetAzureMapsKey(ApiKey: Text)
    begin
        if ApiKey = '' then
            Error('Azure Maps API key cannot be blank.');

        IsolatedStorage.SetEncrypted(GetApiKeyName(), ApiKey, DataScope::Company);
    end;

    procedure ClearAzureMapsKey()
    begin
        if IsolatedStorage.Contains(GetApiKeyName(), DataScope::Company) then
            IsolatedStorage.Delete(GetApiKeyName(), DataScope::Company);
    end;

    procedure HasAzureMapsKey(): Boolean
    begin
        exit(IsolatedStorage.Contains(GetApiKeyName(), DataScope::Company));
    end;

    procedure RefreshComparisonRoutes(var CompareHeader: Record "GPI Pack Compare")
    var
        CompareLine: Record "GPI Pack Comp Line";
    begin
        CompareHeader.TestField("Destination Latitude");
        CompareHeader.TestField("Destination Longitude");

        CompareLine.SetRange("Compare Entry No.", CompareHeader."Entry No.");
        if not CompareLine.FindSet(true) then
            Error('Add at least one candidate before refreshing route mileage.');

        repeat
            ResolveRouteForLine(CompareHeader, CompareLine);
            CompareLine.Modify(false);
        until CompareLine.Next() = 0;

        CompareHeader."Last Calculated At" := 0DT;
        CompareHeader."Last Calculated By" := '';
        CompareHeader.Modify(false);
    end;

    procedure ResolveRouteForLine(CompareHeader: Record "GPI Pack Compare"; var CompareLine: Record "GPI Pack Comp Line"): Boolean
    var
        Cache: Record "GPI Route Cache";
        Setup: Record "GPI Route Setup";
        DistanceMiles: Decimal;
        DurationMinutes: Decimal;
        ProviderReference: Text[100];
        RouteMessage: Text[250];
    begin
        ClearRouteResult(CompareLine);

        if (CompareLine."Origin Latitude" = 0) or (CompareLine."Origin Longitude" = 0) then begin
            CompareLine."Route Message" := 'Origin latitude and longitude are required on the vendor FOB location.';
            exit(false);
        end;

        if (CompareHeader."Destination Latitude" = 0) or (CompareHeader."Destination Longitude" = 0) then begin
            CompareLine."Route Message" := 'Destination latitude and longitude are required on the sourcing comparison.';
            exit(false);
        end;

        if TryGetCachedRoute(
            CompareLine."Origin Latitude",
            CompareLine."Origin Longitude",
            CompareHeader."Destination Latitude",
            CompareHeader."Destination Longitude",
            CompareLine.Mode,
            Cache)
        then begin
            ApplyCacheToLine(Cache, CompareLine);
            exit(true);
        end;

        EnsureSetup(Setup);
        if not Setup.Enabled then begin
            CompareLine."Route Message" := 'Route service is not enabled. A cached or manually seeded route may still be used.';
            exit(false);
        end;

        case Setup.Provider of
            "GPI Route Provider"::"Azure Maps":
                begin
                    if not CallAzureMaps(
                        Setup,
                        CompareLine."Origin Latitude",
                        CompareLine."Origin Longitude",
                        CompareHeader."Destination Latitude",
                        CompareHeader."Destination Longitude",
                        CompareLine.Mode,
                        DistanceMiles,
                        DurationMinutes,
                        ProviderReference,
                        RouteMessage)
                    then begin
                        CompareLine."Route Message" := RouteMessage;
                        exit(false);
                    end;

                    SaveRouteCache(
                        Setup,
                        CompareLine."Origin Latitude",
                        CompareLine."Origin Longitude",
                        CompareHeader."Destination Latitude",
                        CompareHeader."Destination Longitude",
                        CompareLine.Mode,
                        DistanceMiles,
                        DurationMinutes,
                        "GPI Route Provider"::"Azure Maps",
                        ProviderReference,
                        'Calculated by Azure Maps Route Directions v2025-01-01.');

                    CompareLine."Route Miles" := DistanceMiles;
                    CompareLine."Route Duration Minutes" := DurationMinutes;
                    CompareLine."Route Provider" := "GPI Route Provider"::"Azure Maps";
                    CompareLine."Route Calculated At" := CurrentDateTime();
                    CompareLine."Route Message" := 'Route mileage calculated by Azure Maps.';
                    exit(true);
                end;
            else begin
                CompareLine."Route Message" := 'The configured route provider does not calculate routes automatically.';
                exit(false);
            end;
        end;
    end;

    local procedure TryGetCachedRoute(OriginLatitude: Decimal; OriginLongitude: Decimal; DestinationLatitude: Decimal; DestinationLongitude: Decimal; TransportMode: Enum "GPI Pack Transport"; var Cache: Record "GPI Route Cache"): Boolean
    begin
        Cache.Reset();
        Cache.SetCurrentKey("Origin Latitude", "Origin Longitude", "Destination Latitude", "Destination Longitude", Mode, "Expires At");
        Cache.SetRange("Origin Latitude", OriginLatitude);
        Cache.SetRange("Origin Longitude", OriginLongitude);
        Cache.SetRange("Destination Latitude", DestinationLatitude);
        Cache.SetRange("Destination Longitude", DestinationLongitude);
        Cache.SetRange(Mode, TransportMode);
        Cache.SetFilter("Expires At", '%1..', CurrentDateTime());
        exit(Cache.FindLast());
    end;

    local procedure ApplyCacheToLine(Cache: Record "GPI Route Cache"; var CompareLine: Record "GPI Pack Comp Line")
    begin
        CompareLine."Route Miles" := Cache."Distance Miles";
        CompareLine."Route Duration Minutes" := Cache."Duration Minutes";
        CompareLine."Route Provider" := Cache.Provider;
        CompareLine."Route Calculated At" := Cache."Calculated At";
        CompareLine."Route Message" := CopyStr(StrSubstNo('Route mileage loaded from cache entry %1.', Cache."Entry No."), 1, MaxStrLen(CompareLine."Route Message"));
    end;

    local procedure SaveRouteCache(Setup: Record "GPI Route Setup"; OriginLatitude: Decimal; OriginLongitude: Decimal; DestinationLatitude: Decimal; DestinationLongitude: Decimal; TransportMode: Enum "GPI Pack Transport"; DistanceMiles: Decimal; DurationMinutes: Decimal; Provider: Enum "GPI Route Provider"; ProviderReference: Text[100]; Notes: Text[250])
    var
        Cache: Record "GPI Route Cache";
        ExpiresAt: DateTime;
    begin
        ExpiresAt := CurrentDateTime() + (Setup."Cache Days" * 24 * 60 * 60 * 1000);

        Cache.SetRange("Origin Latitude", OriginLatitude);
        Cache.SetRange("Origin Longitude", OriginLongitude);
        Cache.SetRange("Destination Latitude", DestinationLatitude);
        Cache.SetRange("Destination Longitude", DestinationLongitude);
        Cache.SetRange(Mode, TransportMode);
        if not Cache.FindFirst() then begin
            Cache.Init();
            Cache."Origin Latitude" := OriginLatitude;
            Cache."Origin Longitude" := OriginLongitude;
            Cache."Destination Latitude" := DestinationLatitude;
            Cache."Destination Longitude" := DestinationLongitude;
            Cache.Mode := TransportMode;
            Cache."Distance Miles" := DistanceMiles;
            Cache."Duration Minutes" := DurationMinutes;
            Cache.Provider := Provider;
            Cache."Calculated At" := CurrentDateTime();
            Cache."Expires At" := ExpiresAt;
            Cache."Provider Reference" := ProviderReference;
            Cache.Notes := Notes;
            Cache.Insert(true);
            exit;
        end;

        Cache."Distance Miles" := DistanceMiles;
        Cache."Duration Minutes" := DurationMinutes;
        Cache.Provider := Provider;
        Cache."Calculated At" := CurrentDateTime();
        Cache."Expires At" := ExpiresAt;
        Cache."Provider Reference" := ProviderReference;
        Cache.Notes := Notes;
        Cache.Modify(true);
    end;

    local procedure CallAzureMaps(Setup: Record "GPI Route Setup"; OriginLatitude: Decimal; OriginLongitude: Decimal; DestinationLatitude: Decimal; DestinationLongitude: Decimal; TransportMode: Enum "GPI Pack Transport"; var DistanceMiles: Decimal; var DurationMinutes: Decimal; var ProviderReference: Text[100]; var RouteMessage: Text[250]): Boolean
    var
        Client: HttpClient;
        Content: HttpContent;
        ContentHeaders: HttpHeaders;
        RequestHeaders: HttpHeaders;
        Response: HttpResponseMessage;
        RequestJson: JsonObject;
        RequestText: Text;
        ResponseText: Text;
        ApiKey: SecretText;
        Endpoint: Text;
    begin
        DistanceMiles := 0;
        DurationMinutes := 0;
        ProviderReference := '';
        RouteMessage := '';

        if not IsolatedStorage.Get(GetApiKeyName(), DataScope::Company, ApiKey) then begin
            RouteMessage := 'Azure Maps API key is not configured in Route Setup.';
            exit(false);
        end;

        Endpoint := Setup.Endpoint;
        if Endpoint = '' then
            Endpoint := 'https://atlas.microsoft.com';
        if CopyStr(Endpoint, StrLen(Endpoint), 1) = '/' then
            Endpoint := CopyStr(Endpoint, 1, StrLen(Endpoint) - 1);

        BuildAzureMapsRequest(OriginLatitude, OriginLongitude, DestinationLatitude, DestinationLongitude, TransportMode, RequestJson);
        RequestJson.WriteTo(RequestText);

        Content.WriteFrom(RequestText);
        Content.GetHeaders(ContentHeaders);
        ContentHeaders.Clear();
        ContentHeaders.Add('Content-Type', 'application/geo+json');

        RequestHeaders := Client.DefaultRequestHeaders();
        RequestHeaders.Add('subscription-key', ApiKey);

        if not Client.Post(Endpoint + '/route/directions?api-version=2025-01-01', Content, Response) then begin
            RouteMessage := 'Azure Maps route request could not be sent. Verify that HttpClient requests are enabled for the extension.';
            exit(false);
        end;

        Response.Content().ReadAs(ResponseText);
        if not Response.IsSuccessStatusCode() then begin
            RouteMessage := CopyStr(StrSubstNo('Azure Maps returned HTTP %1. %2', Response.HttpStatusCode(), ResponseText), 1, MaxStrLen(RouteMessage));
            exit(false);
        end;

        if not ParseAzureMapsResponse(ResponseText, DistanceMiles, DurationMinutes) then begin
            RouteMessage := 'Azure Maps returned a successful response but no route distance could be parsed.';
            exit(false);
        end;

        ProviderReference := CopyStr(StrSubstNo('%1-%2', Format(OriginLatitude), Format(DestinationLatitude)), 1, MaxStrLen(ProviderReference));
        exit(true);
    end;

    local procedure BuildAzureMapsRequest(OriginLatitude: Decimal; OriginLongitude: Decimal; DestinationLatitude: Decimal; DestinationLongitude: Decimal; TransportMode: Enum "GPI Pack Transport"; var RequestJson: JsonObject)
    var
        Features: JsonArray;
        RouteOutputOptions: JsonArray;
        OriginFeature: JsonObject;
        DestinationFeature: JsonObject;
    begin
        Clear(RequestJson);
        BuildWaypointFeature(OriginLatitude, OriginLongitude, 0, OriginFeature);
        BuildWaypointFeature(DestinationLatitude, DestinationLongitude, 1, DestinationFeature);
        Features.Add(OriginFeature);
        Features.Add(DestinationFeature);
        RouteOutputOptions.Add('routePath');

        RequestJson.Add('type', 'FeatureCollection');
        RequestJson.Add('features', Features);
        RequestJson.Add('optimizeRoute', 'fastestWithoutTraffic');
        RequestJson.Add('routeOutputOptions', RouteOutputOptions);
        RequestJson.Add('travelMode', GetAzureMapsTravelMode(TransportMode));
    end;

    local procedure BuildWaypointFeature(Latitude: Decimal; Longitude: Decimal; PointIndex: Integer; var Feature: JsonObject)
    var
        Geometry: JsonObject;
        Coordinates: JsonArray;
        Properties: JsonObject;
    begin
        Clear(Feature);
        Coordinates.Add(Longitude);
        Coordinates.Add(Latitude);
        Geometry.Add('type', 'Point');
        Geometry.Add('coordinates', Coordinates);
        Properties.Add('pointIndex', PointIndex);
        Properties.Add('pointType', 'waypoint');
        Feature.Add('type', 'Feature');
        Feature.Add('geometry', Geometry);
        Feature.Add('properties', Properties);
    end;

    local procedure GetAzureMapsTravelMode(TransportMode: Enum "GPI Pack Transport"): Text
    begin
        case TransportMode of
            "GPI Pack Transport"::TL,
            "GPI Pack Transport"::CNTR:
                exit('truck');
            else
                exit('driving');
        end;
    end;

    local procedure ParseAzureMapsResponse(ResponseText: Text; var DistanceMiles: Decimal; var DurationMinutes: Decimal): Boolean
    var
        Root: JsonObject;
        Token: JsonToken;
        Features: JsonArray;
        FeatureToken: JsonToken;
        Feature: JsonObject;
        Properties: JsonObject;
        ValueToken: JsonToken;
        FeatureType: Text;
        DistanceMeters: Decimal;
        DurationSeconds: Decimal;
        Index: Integer;
    begin
        if not Root.ReadFrom(ResponseText) then
            exit(false);
        if not Root.Get('features', Token) then
            exit(false);
        if not Token.IsArray() then
            exit(false);

        Features := Token.AsArray();
        for Index := 0 to Features.Count() - 1 do begin
            Features.Get(Index, FeatureToken);
            if FeatureToken.IsObject() then begin
                Feature := FeatureToken.AsObject();
                if Feature.Get('properties', Token) and Token.IsObject() then begin
                    Properties := Token.AsObject();
                    FeatureType := '';
                    if Properties.Get('type', ValueToken) and ValueToken.IsValue() then
                        FeatureType := ValueToken.AsValue().AsText();

                    if FeatureType = 'RoutePath' then begin
                        if Properties.Get('distanceInMeters', ValueToken) and ValueToken.IsValue() then
                            DistanceMeters := ValueToken.AsValue().AsDecimal();
                        if Properties.Get('durationInSeconds', ValueToken) and ValueToken.IsValue() then
                            DurationSeconds := ValueToken.AsValue().AsDecimal();

                        if DistanceMeters > 0 then begin
                            DistanceMiles := Round(DistanceMeters / 1609.344, 0.01, '=');
                            DurationMinutes := Round(DurationSeconds / 60, 0.1, '=');
                            exit(true);
                        end;
                    end;
                end;
            end;
        end;

        exit(false);
    end;

    local procedure ClearRouteResult(var CompareLine: Record "GPI Pack Comp Line")
    begin
        CompareLine."Route Miles" := 0;
        CompareLine."Route Duration Minutes" := 0;
        CompareLine."Route Provider" := "GPI Route Provider"::Manual;
        CompareLine."Route Calculated At" := 0DT;
        CompareLine."Route Message" := '';
    end;

    local procedure GetApiKeyName(): Text
    begin
        exit('GPI-AZURE-MAPS-SUBSCRIPTION-KEY');
    end;
}
