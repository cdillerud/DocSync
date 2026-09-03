/// <summary>
/// Read-only diagnostic API over the Business Central Event Subscription virtual table.
/// Used to identify active extension subscribers that may affect Sales Line pricing or order-entry behavior.
/// </summary>
page 71206 "GPI Order Intake Event Subs"
{
    Caption = 'GPI Order Intake Event Subscriptions';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'orderIntake';
    APIVersion = 'v1.0';
    EntityName = 'orderIntakeEventSubscription';
    EntitySetName = 'orderIntakeEventSubscriptions';
    SourceTable = "Event Subscription";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(Subscriptions)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                    Editable = false;
                }
                field(subscriberCodeunitId; Rec."Subscriber Codeunit ID")
                {
                    Caption = 'Subscriber Codeunit ID';
                    Editable = false;
                }
                field(subscriberFunction; Rec."Subscriber Function")
                {
                    Caption = 'Subscriber Function';
                    Editable = false;
                }
                field(eventType; Rec."Event Type")
                {
                    Caption = 'Event Type';
                    Editable = false;
                }
                field(publisherObjectType; Rec."Publisher Object Type")
                {
                    Caption = 'Publisher Object Type';
                    Editable = false;
                }
                field(publisherObjectId; Rec."Publisher Object ID")
                {
                    Caption = 'Publisher Object ID';
                    Editable = false;
                }
                field(publishedFunction; Rec."Published Function")
                {
                    Caption = 'Published Function';
                    Editable = false;
                }
                field(active; Rec.Active)
                {
                    Caption = 'Active';
                    Editable = false;
                }
                field(numberOfCalls; Rec."Number of Calls")
                {
                    Caption = 'Number of Calls';
                    Editable = false;
                }
                field(errorInformation; Rec."Error Information")
                {
                    Caption = 'Error Information';
                    Editable = false;
                }
                field(originatingPackageId; Rec."Originating Package ID")
                {
                    Caption = 'Originating Package ID';
                    Editable = false;
                }
                field(originatingAppName; Rec."Originating App Name")
                {
                    Caption = 'Originating App Name';
                    Editable = false;
                }
                field(subscriberInstance; Rec."Subscriber Instance")
                {
                    Caption = 'Subscriber Instance';
                    Editable = false;
                }
                field(activeManualInstances; Rec."Active Manual Instances")
                {
                    Caption = 'Active Manual Instances';
                    Editable = false;
                }
            }
        }
    }
}
