/// <summary>
/// Page 50100 "GPI Document Link Factbox"
/// CardPart factbox embedding the GPI Hub document viewer via iframe.
/// No SourceTable — the factbox loads documents from the Hub API directly.
/// Supports viewing linked documents, uploading, and removing links.
/// </summary>
page 50100 "GPI Document Link Factbox"
{
    Caption = 'GPI Documents';
    PageType = CardPart;
    Editable = false;
    RefreshOnActivate = true;

    layout
    {
        area(Content)
        {
            usercontrol(GPIDocViewer; "Microsoft.Dynamics.Nav.Client.WebPageViewer")
            {
                ApplicationArea = All;

                trigger ControlAddInReady(callbackUrl: Text)
                begin
                    IsControlReady := true;
                    NavigateToFactbox();
                end;

                trigger Callback(data: Text)
                begin
                    // Handle messages from the iframe if needed
                end;
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(RefreshLinks)
            {
                ApplicationArea = All;
                Caption = 'Refresh';
                Image = Refresh;
                ToolTip = 'Refresh document links from GPI Hub';

                trigger OnAction()
                begin
                    NavigateToFactbox();
                end;
            }
        }
    }

    var
        CurrentDocType: Enum "GPI Doc Link Type";
        CurrentBCDocumentNo: Code[20];
        CurrentVendorContext: Text;
        IsControlReady: Boolean;

    /// <summary>
    /// Set the context for this factbox from the parent page extension.
    /// Called by the page extension's OnAfterGetCurrRecord.
    /// </summary>
    procedure SetContext(DocType: Enum "GPI Doc Link Type"; BCDocNo: Code[20]; VendorCtx: Text)
    begin
        CurrentDocType := DocType;
        CurrentBCDocumentNo := BCDocNo;
        CurrentVendorContext := VendorCtx;
        NavigateToFactbox();
    end;

    local procedure NavigateToFactbox()
    var
        GPILinkMgt: Codeunit "GPI Document Link Mgt";
        HubBaseUrl: Text;
        BCEntity: Text;
        FactboxUrl: Text;
    begin
        if not IsControlReady then
            exit;
        if CurrentBCDocumentNo = '' then
            exit;

        HubBaseUrl := GPILinkMgt.GetHubBaseUrl();
        BCEntity := GetBCEntityFromDocType(CurrentDocType);

        FactboxUrl := HubBaseUrl + '/api/gpi-integration/factbox-ui/' + BCEntity + '/' + CurrentBCDocumentNo;

        CurrPage.GPIDocViewer.Navigate(FactboxUrl);
    end;

    local procedure GetBCEntityFromDocType(DocType: Enum "GPI Doc Link Type"): Text
    begin
        case DocType of
            "GPI Doc Link Type"::"Purchase Invoice":
                exit('purchaseInvoices');
            "GPI Doc Link Type"::"Posted Purchase Invoice":
                exit('purchaseInvoices');
            "GPI Doc Link Type"::"Sales Order":
                exit('salesOrders');
            "GPI Doc Link Type"::"Posted Sales Invoice":
                exit('salesInvoices');
            "GPI Doc Link Type"::"Purchase Order":
                exit('purchaseOrders');
            else
                exit('documents');
        end;
    end;
}
