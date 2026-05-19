page 70150000 "GPI Doc Delivery Setup"
{
    PageType = Card;
    SourceTable = "GPI Doc Delivery Setup";
    Caption = 'GPI Document Delivery Setup';
    UsageCategory = Administration;
    ApplicationArea = All;
    InsertAllowed = false;
    DeleteAllowed = false;

    layout
    {
        area(Content)
        {
            group(General)
            {
                Caption = 'General';

                field("Integration Enabled"; Rec."Integration Enabled")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether Business Central should send document delivery events to GPI Hub. This is disabled by default.';
                }
                field("Hub Base URL"; Rec."Hub Base URL")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the base URL for GPI Hub.';
                }
                field("API Key"; Rec."API Key")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the shared API key used to authenticate to GPI Hub.';
                }
                field("Log Successful Events"; Rec."Log Successful Events")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies whether successful events should be logged locally in Business Central.';
                }
            }

            group("BC Context")
            {
                Caption = 'Business Central Context';

                field("Environment Name"; Rec."Environment Name")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Business Central environment name to include in event payloads.';
                }
                field("Company ID"; Rec."Company ID")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Business Central company ID to include in event payloads.';
                }
                field("Company Name"; Rec."Company Name")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Business Central company name to include in event payloads.';
                }
            }

            group("External Document Link")
            {
                Caption = 'External Document Link';

                field("Document Storage Provider"; Rec."Document Storage Provider")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the external document storage label to include in event metadata.';
                }
                field("Document Link Template"; Rec."Document Link Template")
                {
                    ApplicationArea = All;
                    ToolTip = 'Optional URL template to include in GPI Hub events. Tokens: {DocumentNo}, {RecordNo}, {FileName}, {CompanyName}, {EnvironmentName}.';
                }
                field("Document Folder Template"; Rec."Document Folder Template")
                {
                    ApplicationArea = All;
                    ToolTip = 'Optional folder path template to include in GPI Hub events. Tokens: {DocumentNo}, {RecordNo}, {FileName}, {CompanyName}, {EnvironmentName}.';
                }
            }

            group(Status)
            {
                Caption = 'Status';

                field("Last Test Status"; Rec."Last Test Status")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows the most recent connection test status.';
                }
                field("Last Test At"; Rec."Last Test At")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows when the most recent connection test ran.';
                }
                field("Last Event Sent At"; Rec."Last Event Sent At")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows when the most recent event send attempt occurred.';
                }
                field("Last Event Error"; Rec."Last Event Error")
                {
                    ApplicationArea = All;
                    ToolTip = 'Shows the most recent event send error.';
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(TestConnection)
            {
                ApplicationArea = All;
                Caption = 'Test Connection';
                Image = TestDatabase;
                ToolTip = 'Tests the connection to the GPI Hub BC document events status endpoint.';

                trigger OnAction()
                var
                    Tester: Codeunit "GPI Doc Delivery Test";
                begin
                    Tester.TestConnection();
                    CurrPage.Update(false);
                end;
            }
            action(SendSampleDeliveryEvent)
            {
                ApplicationArea = All;
                Caption = 'Send Sample Delivery Event';
                Image = SendTo;
                ToolTip = 'Sends a sample delivery-sent event to GPI Hub. Integration Enabled must be turned on.';

                trigger OnAction()
                var
                    Tester: Codeunit "GPI Doc Delivery Test";
                begin
                    Tester.SendSampleDeliverySentEvent();
                    CurrPage.Update(false);
                end;
            }
            action(OpenEventLog)
            {
                ApplicationArea = All;
                Caption = 'Open Event Log';
                Image = Log;
                RunObject = page "GPI Doc Delivery Log";
                ToolTip = 'Opens the local Business Central log for GPI Hub document delivery events.';
            }
        }
    }

    trigger OnOpenPage()
    begin
        if not Rec.Get('SETUP') then begin
            Rec.Init();
            Rec."Primary Key" := 'SETUP';
            Rec."Integration Enabled" := false;
            Rec."Log Successful Events" := true;
            Rec."Document Storage Provider" := 'External Link';
            Rec.Insert(true);
        end;
    end;
}
