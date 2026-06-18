codeunit 70518 "GPI Archive File Scenario" implements "File Scenario"
{
    procedure BeforeAddOrModifyFileScenarioCheck(Scenario: Enum "File Scenario"; Connector: Enum "Ext. File Storage Connector") SkipInsertOrModify: Boolean
    begin
        exit(false);
    end;

    procedure GetAdditionalScenarioSetup(Scenario: Enum "File Scenario"; Connector: Enum "Ext. File Storage Connector") SetupExist: Boolean
    begin
        exit(false);
    end;

    procedure BeforeDeleteFileScenarioCheck(Scenario: Enum "File Scenario"; Connector: Enum "Ext. File Storage Connector") SkipDelete: Boolean
    begin
        exit(false);
    end;

    procedure BeforeReassignFileScenarioCheck(Scenario: Enum "File Scenario") SkipReassign: Boolean
    begin
        exit(false);
    end;
}
