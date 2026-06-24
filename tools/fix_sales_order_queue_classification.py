#!/usr/bin/env python3
"""Patch sales-order queue classification precedence safely and idempotently."""

from __future__ import annotations

import argparse
from pathlib import Path

HELPERS = '''

_NORMALIZED_SALES_ORDER_TYPES = {
    "SALES_ORDER",
    "SALESORDER",
    "CUSTOMER_PO",
    "CUSTOMER_PURCHASE_ORDER",
}


def _normalize_document_type(value: Any) -> str:
    if not value:
        return ""
    return str(value).strip().upper().replace("-", "_").replace(" ", "_")


def _effective_document_type(doc: Dict[str, Any]) -> str:
    """Return the first populated classification using current-field precedence."""

    classification = doc.get("classification") or {}
    values = [
        doc.get("doc_type"),
        doc.get("document_type"),
        doc.get("suggested_job_type"),
        classification.get("suggested_type")
        if isinstance(classification, dict)
        else None,
    ]
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""
'''

FILTER = '''
    combined = [
        (collection_name, doc)
        for collection_name, doc in combined
        if _normalize_document_type(_effective_document_type(doc))
        in _NORMALIZED_SALES_ORDER_TYPES
    ]
'''

OLD_QUEUE_TYPE = '''        "document_type": (
            doc.get("document_type")
            or doc.get("doc_type")
            or doc.get("suggested_job_type")
        ),'''

NEW_QUEUE_TYPE = '''        "document_type": _effective_document_type(doc),'''


def patch_root(root: Path) -> None:
    path = root / "backend/services/sales_order_review_service.py"
    if not path.is_file():
        raise SystemExit(f"Missing service file: {path}")

    text = path.read_text(encoding="utf-8")
    original = text

    if "def _effective_document_type(" not in text:
        marker = "]\n\n\n@dataclass\nclass LocatedDocument:"
        if marker not in text:
            raise SystemExit(f"Could not locate helper insertion point in {path}")
        text = text.replace(
            marker,
            "]" + HELPERS + "\n\n@dataclass\nclass LocatedDocument:",
            1,
        )

    if "if _normalize_document_type(_effective_document_type(doc))" not in text:
        marker = '''    combined: List[Tuple[str, Dict[str, Any]]] = [
        ("sales_documents", doc) for doc in sales_docs
    ] + [("hub_documents", doc) for doc in hub_docs]
'''
        if marker not in text:
            raise SystemExit(f"Could not locate queue combination block in {path}")
        text = text.replace(marker, marker + FILTER, 1)

    if OLD_QUEUE_TYPE in text:
        text = text.replace(OLD_QUEUE_TYPE, NEW_QUEUE_TYPE, 1)
    elif NEW_QUEUE_TYPE not in text:
        raise SystemExit(f"Could not locate queue document type block in {path}")

    compile(text, str(path), "exec")

    if text == original:
        print(f"Already patched: {path}")
        return

    backup = path.with_suffix(path.suffix + ".before-effective-type.bak")
    if not backup.exists():
        backup.write_text(original, encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    print(f"Patched: {path}")
    print(f"Backup:  {backup}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "roots",
        nargs="+",
        type=Path,
        help="Repository/worktree roots to patch",
    )
    args = parser.parse_args()

    for root in args.roots:
        patch_root(root.resolve())


if __name__ == "__main__":
    main()
