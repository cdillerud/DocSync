/// <summary>
/// API Page 50110 "GPI Document Link API"
/// REST API endpoint for GPI Document Hub to create/update document links.
/// 
/// Endpoint: /api/gpi/documents/v1.0/companies({companyId})/documentLinks
/// Supports: GET, POST, PATCH, DELETE
/// </summary>
page 50110 "GPI Document Link API"
{
    Caption = 'GPI Document Links API';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'documents';
    APIVersion = 'v1.0';
    EntitySetName = 'documentLinks';
    EntityName = 'documentLink';
    SourceTable = "GPI Document Link";
    DelayedInsert = true;
    ODataKeyFields = SystemId;

    layout
    {
        area(Content)
        {
            repeater(Links)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                    Editable = false;
                }
                field(entryNo; Rec."Entry No.")
                {
                    Caption = 'Entry No.';
                    Editable = false;
                }
                field(documentType; Rec."Document Type")
                {
                    Caption = 'Document Type';
                }
                field(targetSystemId; Rec."Target SystemId")
                {
                    Caption = 'Target System ID';
                }
                field(bcDocumentNo; Rec."BC Document No.")
                {
                    Caption = 'BC Document No.';
                }
                field(sharePointUrl; Rec."SharePoint Url")
                {
                    Caption = 'SharePoint URL';
                }
                field(sharePointDriveId; Rec."SharePoint Drive Id")
                {
                    Caption = 'SharePoint Drive ID';
                }
                field(sharePointItemId; Rec."SharePoint Item Id")
                {
                    Caption = 'SharePoint Item ID';
                }
                field(uploadedAt; Rec."Uploaded At")
                {
                    Caption = 'Uploaded At';
                }
                field(uploadedBy; Rec."Uploaded By")
                {
                    Caption = 'Uploaded By';
                }
                field(source; Rec.Source)
                {
                    Caption = 'Source';
                }
                field(lastError; Rec."Last Error")
                {
                    Caption = 'Last Error';
                }
            }
        }
    }
}
