page 70150001 "GPI Doc Delivery Log"
{
    PageType = List;
    SourceTable = "GPI Doc Delivery Log";
    Caption = 'GPI Document Delivery Log';
    UsageCategory = History;
    ApplicationArea = All;
    Editable = false;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;

    layout
    {
        area(Content)
        {
            repeater(Events)
            {
                field("Entry No."; Rec."Entry No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the log entry number.';
                }
                field("Created At"; Rec."Created At")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies when this log entry was created.';
                }
                field(Success; Rec.Success)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether the event was sent successfully.';
                }
                field(Duplicate; Rec.Duplicate)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether GPI Hub treated the event as a duplicate.';
                }
                field("HTTP Status Code"; Rec."HTTP Status Code")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the HTTP status code returned by GPI Hub.';
                }
                field("Event Type"; Rec."Event Type")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the event type sent to GPI Hub.';
                }
                field("Event ID"; Rec."Event ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the event ID sent to GPI Hub.';
                }
                field("Correlation ID"; Rec."Correlation ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the correlation ID for the event.';
                }
                field("BC Record Type"; Rec."BC Record Type")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Business Central record type.';
                }
                field("BC Record No."; Rec."BC Record No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Business Central record number.';
                }
                field("Document Type"; Rec."Document Type")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the GPI Hub document type.';
                }
                field("File Name"; Rec."File Name")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the file name included in the event.';
                }
                field("Hub Document ID"; Rec."Hub Document ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the GPI Hub document ID returned by the API.';
                }
                field("Error Message"; Rec."Error Message")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies any error returned by GPI Hub or the HTTP client.';
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(ViewResponseBody)
            {
                ApplicationArea = All;
                Caption = 'View Response Body';
                Image = View;
                ToolTip = 'Shows the full response body returned by GPI Hub.';

                trigger OnAction()
                var
                    ResponseText: Text;
                begin
                    ResponseText := Rec.GetResponseBody();
                    if ResponseText = '' then
                        Message('No response body was stored for this log entry.')
                    else
                        Message(ResponseText);
                end;
            }
        }
    }
}
