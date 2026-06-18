controladdin "GPI Document Drop Zone"
{
    Scripts = 'src/controladdin/GPIDocumentDropZone.js';
    StartupScript = 'src/controladdin/GPIDocumentDropZoneStartup.js';
    StyleSheets = 'src/controladdin/GPIDocumentDropZone.css';

    RequestedHeight = 135;
    MinimumHeight = 110;
    MaximumHeight = 180;
    RequestedWidth = 320;
    MinimumWidth = 250;
    HorizontalStretch = true;
    VerticalStretch = false;

    event ControlReady();
    event FileDropped(FileName: Text; ContentType: Text; Base64Content: Text; FileSize: Integer);

    procedure SetContext(ContextCaption: Text; DocumentCount: Integer; IsContextReady: Boolean);
    procedure SetBusy(IsBusy: Boolean);
    procedure NotifyResult(IsSuccess: Boolean; MessageText: Text; DocumentCount: Integer);
}
