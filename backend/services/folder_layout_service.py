"""AP Temp Folder layout, as Meghan Czajkowski set it out (2026-11-06).

The Hub routes, learns and measures in the layout staff file in today
("Dropship Not International/Freight", ...). This module maps a routed
path to the new layout only where the Hub writes to SharePoint, and maps
staff filings made in the new layout back, so learning and the accuracy
numbers keep one vocabulary across the cutover.

Moved now (no open question):
  Dropship Not International/Freight              -> Freight
  Dropship Not International/Drop Ship All Others -> Drop Ship Domestic All Others
  Dropship Not International/Drop Ship Dunnage Vendors -> Drop Ship Domestic Dunnage
  Warehouse Not International/Assembly GT B&B, Assembly Kent -> Warehouse Assembly Orders
  any domestic document referencing a WA order (WA2334...) -> Warehouse Assembly Orders
    (staff filed 95 of 117 WA documents under Assembly, 90 days to 2026-11-06)
Waiting on Meghan: where Ball / Canpack / root Dropship Not International
and the Warehouse Not International root / Ball Orders go (dunnage vs all
others), and which subfolders stay. Those paths are written unchanged.
"""
import re
from typing import Any, Dict, Optional

NEW_LAYOUT = True
ASSEMBLY = "Warehouse Assembly Orders"
MOVES = [
    ("Dropship Not International/Freight", "Freight"),
    ("Dropship Not International/Drop Ship All Others", "Drop Ship Domestic All Others"),
    ("Dropship Not International/Drop Ship Dunnage Vendors", "Drop Ship Domestic Dunnage"),
    ("Warehouse Not International/Assembly GT B&B", ASSEMBLY),
    ("Warehouse Not International/Assembly Kent", ASSEMBLY),
    ("Warehouse Not International/Assembly", ASSEMBLY),
]
# New top folder -> the folder staff used for it before (for learning).
BACK = {
    "freight": "Dropship Not International/Freight",
    "drop ship domestic all others": "Dropship Not International/Drop Ship All Others",
    "drop ship domestic dunnage": "Dropship Not International/Drop Ship Dunnage Vendors",
    "warehouse assembly orders": "Warehouse Not International/Assembly GT B&B",   # 123 of 156 assembly filings
}
_DOMESTIC = ("dropship not international", "warehouse not international")
_WA = re.compile(r"(?<![A-Z0-9])WA\d{4,}(?!\d)", re.I)
_BASE = "temp folder"


def _parts(path: Any):
    return [p for p in str(path or "").split("/") if p]


def _lead(path: Any) -> str:
    return "/" if str(path or "").startswith("/") else ""


def to_new(path: Optional[str]) -> Optional[str]:
    """Old-layout path -> new-layout path (base folder and subpath kept)."""
    if not NEW_LAYOUT or not path:
        return path
    parts = _parts(path)
    low = [p.lower() for p in parts]
    i = 1 if low and low[0] == _BASE else 0
    for old, new in MOVES:
        o = old.lower().split("/")
        if low[i:i + len(o)] == o:
            return _lead(path) + "/".join(parts[:i] + new.split("/") + parts[i + len(o):])
    return path


def to_old(path: Optional[str]) -> Optional[str]:
    """A staff filing in the new layout -> the old-layout path the Hub learns in."""
    if not path:
        return path
    parts = _parts(path)
    low = [p.lower() for p in parts]
    i = 1 if low and low[0] == _BASE else 0
    if len(low) > i and low[i] in BACK:
        return _lead(path) + "/".join(parts[:i] + BACK[low[i]].split("/") + parts[i + 1:])
    return path


def wa_orders(doc: Optional[Dict[str, Any]]) -> list:
    """WA (warehouse assembly) order numbers the document references."""
    if not doc:
        return []
    ex = doc.get("extracted_fields") or {}
    pc = doc.get("po_correction") or {}
    text = " ".join(str(x or "") for x in (
        doc.get("file_name"), ex.get("po_number"), ex.get("order_number"), ex.get("reference_number"),
        ex.get("purchase_order"), pc.get("gamer_order"), doc.get("resolved_po_number")))
    return sorted({m.upper() for m in _WA.findall(text)})


def final_path(doc: Optional[Dict[str, Any]], path: Optional[str]) -> Optional[str]:
    """Where the Hub writes the document in SharePoint."""
    if not NEW_LAYOUT or not path:
        return path
    parts = _parts(path)
    low = [p.lower() for p in parts]
    i = 1 if low and low[0] == _BASE else 0
    if len(low) > i and low[i] in _DOMESTIC and wa_orders(doc):
        return _lead(path) + "/".join(parts[:i] + [ASSEMBLY])
    return to_new(path)
