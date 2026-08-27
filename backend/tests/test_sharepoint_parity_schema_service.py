from services.sharepoint_parity_schema_service import (
    PARITY_COLUMN_TYPES,
    validate_parity_columns,
)


def _column(name, facet, *, read_only=False):
    return {
        "name": name,
        "displayName": name,
        facet: {},
        "readOnly": read_only,
    }


def _compatible_columns():
    columns = []
    preferred = {
        "GPI_SourceTableID": "number",
        "GPI_SourceSystemId": "text",
        "GPI_SourceDocumentType": "text",
        "GPI_SourceDocumentNo": "text",
        "GPI_SourcePartyType": "text",
        "GPI_SourcePartyNo": "text",
        "GPI_OriginalFileName": "text",
        "GPI_SharePointFileName": "text",
        "GPI_SharePointPath": "multilineText",
        "GPI_SharePointURL": "hyperlinkOrPicture",
        "GPI_Status": "text",
        "GPI_MatchStatus": "text",
        "GPI_MatchMethod": "text",
        "GPI_MatchConfidence": "number",
        "GPI_Candidates": "multilineText",
        "ImportReady": "boolean",
    }
    for name in PARITY_COLUMN_TYPES:
        columns.append(_column(name, preferred[name]))
    return columns


def test_complete_compatible_schema_is_ready():
    result = validate_parity_columns(_compatible_columns())
    assert result["ready"] is True
    assert result["missing"] == []
    assert result["incompatible"] == []
    assert result["matched_count"] == result["required_count"] == 16


def test_missing_internal_column_fails_closed():
    columns = _compatible_columns()
    columns = [c for c in columns if c["name"] != "GPI_SourceSystemId"]
    result = validate_parity_columns(columns)
    assert result["ready"] is False
    assert result["missing"] == ["GPI_SourceSystemId"]


def test_wrong_internal_name_does_not_match_display_name():
    columns = _compatible_columns()
    for column in columns:
        if column["name"] == "GPI_SourceSystemId":
            column["name"] = "GPI_x005f_SourceSystemId"
            column["displayName"] = "GPI_SourceSystemId"
    result = validate_parity_columns(columns)
    assert result["ready"] is False
    assert "GPI_SourceSystemId" in result["missing"]


def test_import_ready_must_be_boolean():
    columns = _compatible_columns()
    for index, column in enumerate(columns):
        if column["name"] == "ImportReady":
            columns[index] = _column("ImportReady", "text")
    result = validate_parity_columns(columns)
    assert result["ready"] is False
    issue = next(i for i in result["incompatible"] if i["name"] == "ImportReady")
    assert issue["actual_facets"] == ["text"]
    assert issue["allowed_types"] == ["boolean"]


def test_read_only_required_column_fails_closed():
    columns = _compatible_columns()
    for index, column in enumerate(columns):
        if column["name"] == "GPI_Status":
            columns[index] = _column("GPI_Status", "text", read_only=True)
    result = validate_parity_columns(columns)
    assert result["ready"] is False
    assert next(i for i in result["incompatible"] if i["name"] == "GPI_Status")["read_only"] is True


def test_source_table_and_confidence_accept_text_or_number():
    columns = _compatible_columns()
    for index, column in enumerate(columns):
        if column["name"] in {"GPI_SourceTableID", "GPI_MatchConfidence"}:
            columns[index] = _column(column["name"], "text")
    result = validate_parity_columns(columns)
    assert result["ready"] is True
