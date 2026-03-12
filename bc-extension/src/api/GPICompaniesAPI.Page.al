page 50111 "GPI Companies API"
{
    Caption = 'GPI Companies API';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'integration';
    APIVersion = 'v1.0';
    EntitySetName = 'companies';
    EntityName = 'company';
    SourceTable = Company;
    Editable = false;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    ODataKeyFields = SystemId;

    layout
    {
        area(Content)
        {
            repeater(Companies)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                }
                field(name; Rec.Name)
                {
                    Caption = 'Name';
                }
                field(displayName; Rec."Display Name")
                {
                    Caption = 'Display Name';
                }
            }
        }
    }
}
