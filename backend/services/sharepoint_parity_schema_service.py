"""Read-only SharePoint parity metadata schema validation.

This service validates the *internal* column names and compatible Graph column
shapes required by the Square9 parity metadata writer. It performs no writes.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set

import httpx


# Graph columnDefinition type facets accepted for each internal field. Text is
# intentionally allowed for SourceTableID and MatchConfidence because the
# metadata writer already emits values compatible with either Text or Number
# columns. ImportReady must remain Boolean so readiness cannot be represented by
# a truthy/non-empty string accidentally.
PARITY_COLUMN_TYPES: Dict[str, Set[str]] = {
    "GPI_SourceTableID": {"number", "text"},
    "GPI_SourceSystemId": {"text"},
    "GPI_SourceDocumentType": {"text", "choice"},
    "GPI_SourceDocumentNo": {"text"},
    "GPI_SourcePartyType": {"text", "choice"},
    "GPI_SourcePartyNo": {"text"},
    "GPI_OriginalFileName": {"text"},
    "GPI_SharePointFileName": {"text"},
    "GPI_SharePointPath": {"text", "multilineText"},
    "GPI_SharePointURL": {"text", "hyperlinkOrPicture", "multilineText"},
    "GPI_Status": {"text", "choice"},
    "GPI_MatchStatus": {"text", "choice"},
    "GPI_MatchMethod": {"text", "choice"},
    "GPI_MatchConfidence": {"number", "text"},
    "GPI_Candidates": {"text", "multilineText"},
    "ImportReady": {"boolean"},
}


def _column_facets(column: Mapping[str, Any]) -> Set[str]:
    """Return Graph type-facet keys present on a columnDefinition."""
    ignored = {
        "id",
        "name",
        "displayName",
        "description",
        "hidden",
        "indexed",
        "readOnly",
        "required",
        "enforceUniqueValues",
        "columnGroup",
    }
    return {
        key
        for key, value in column.items()
        if key not in ignored and value is not None
    }


def validate_parity_columns(columns: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate required internal names and compatible Graph column types."""
    by_name = {
        str(column.get("name") or ""): dict(column)
        for column in columns
        if str(column.get("name") or "").strip()
    }

    missing: List[str] = []
    incompatible: List[Dict[str, Any]] = []
    matched: List[Dict[str, Any]] = []

    for internal_name, allowed_types in PARITY_COLUMN_TYPES.items():
        column = by_name.get(internal_name)
        if not column:
            missing.append(internal_name)
            continue

        facets = _column_facets(column)
        compatible = sorted(facets.intersection(allowed_types))
        if not compatible:
            incompatible.append(
                {
                    "name": internal_name,
                    "display_name": column.get("displayName", ""),
                    "allowed_types": sorted(allowed_types),
                    "actual_facets": sorted(facets),
                    "read_only": bool(column.get("readOnly")),
                }
            )
            continue

        if column.get("readOnly"):
            incompatible.append(
                {
                    "name": internal_name,
                    "display_name": column.get("displayName", ""),
                    "allowed_types": sorted(allowed_types),
                    "actual_facets": sorted(facets),
                    "read_only": True,
                }
            )
            continue

        matched.append(
            {
                "name": internal_name,
                "display_name": column.get("displayName", ""),
                "type": compatible[0],
            }
        )

    return {
        "ready": not missing and not incompatible,
        "required_count": len(PARITY_COLUMN_TYPES),
        "matched_count": len(matched),
        "missing": missing,
        "incompatible": incompatible,
        "matched": matched,
    }


async def validate_live_sharepoint_parity_schema() -> Dict[str, Any]:
    """Read the configured SharePoint library schema from Graph and validate it.

    The configured target is inherited from ``sharepoint_service``. The method
    performs GET requests only: site/drive discovery, drive->list discovery,
    and list column enumeration.
    """
    from services import sharepoint_service

    token = await sharepoint_service._get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        site_id, drive_id = await sharepoint_service._resolve_site_and_drive(client, token)
        headers = {"Authorization": f"Bearer {token}"}

        list_resp = await client.get(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/list",
            headers=headers,
        )
        list_data = list_resp.json() if list_resp.content else {}
        if list_resp.status_code != 200 or "id" not in list_data:
            error = list_data.get("error", {}) if isinstance(list_data, dict) else {}
            raise RuntimeError(
                "SharePoint parity schema preflight could not resolve the document "
                f"library list (HTTP {list_resp.status_code}): "
                f"{error.get('message', error.get('code', list_resp.text[:300]))}"
            )

        list_id = list_data["id"]
        columns: List[Dict[str, Any]] = []
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/columns?$top=999"
        while url:
            columns_resp = await client.get(url, headers=headers)
            columns_data = columns_resp.json() if columns_resp.content else {}
            if columns_resp.status_code != 200:
                error = columns_data.get("error", {}) if isinstance(columns_data, dict) else {}
                raise RuntimeError(
                    "SharePoint parity schema preflight could not enumerate columns "
                    f"(HTTP {columns_resp.status_code}): "
                    f"{error.get('message', error.get('code', columns_resp.text[:300]))}"
                )
            columns.extend(columns_data.get("value", []))
            url = columns_data.get("@odata.nextLink")

    result = validate_parity_columns(columns)
    result.update(
        {
            "target": sharepoint_service.SHAREPOINT_TARGET,
            "hostname": sharepoint_service.SHAREPOINT_SITE_HOSTNAME,
            "site_path": sharepoint_service.SHAREPOINT_SITE_PATH,
            "library_name": sharepoint_service.SHAREPOINT_LIBRARY_NAME,
            "base_folder": sharepoint_service.SHAREPOINT_BASE_FOLDER,
            "site_id": site_id,
            "drive_id": drive_id,
            "list_id": list_id,
            "column_count": len(columns),
        }
    )
    return result


__all__ = [
    "PARITY_COLUMN_TYPES",
    "validate_parity_columns",
    "validate_live_sharepoint_parity_schema",
]
