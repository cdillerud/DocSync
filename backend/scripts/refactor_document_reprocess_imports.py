#!/usr/bin/env python3
"""Apply the document reprocess service extraction safely.

This script performs narrow, repeatable source edits:

1. Redirect document router reprocessing to document_reprocess_service.
2. Redirect readiness reprocessing to document_reprocess_service.
3. Remove the remaining server.py workflow-status import from document_handlers.
4. Replace server.py's reprocess implementation with compatibility wrappers.

Run from the repository root. The script refuses to continue when an expected
source pattern is missing, preventing a partial or ambiguous migration.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_exact(path: Path, old: str, new: str) -> None:
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one occurrence in {path}: {old!r}; found {count}"
        )
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    print(f"updated {path.relative_to(ROOT)}")


def replace_function(path: Path, function_name: str, replacement: str) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one function {function_name!r} in {path}; found {len(matches)}"
        )

    node = matches[0]
    lines = source.splitlines(keepends=True)
    start = node.lineno - 1
    end = node.end_lineno
    replacement_text = replacement.rstrip() + "\n\n"
    lines[start:end] = [replacement_text]
    path.write_text("".join(lines), encoding="utf-8")
    print(f"replaced {function_name} in {path.relative_to(ROOT)}")


def main() -> None:
    documents_router = ROOT / "backend/routers/documents.py"
    readiness_router = ROOT / "backend/routers/readiness.py"
    handlers = ROOT / "backend/services/document_handlers.py"
    server = ROOT / "backend/server.py"

    replace_exact(
        documents_router,
        "from server import reprocess_document",
        "from services.document_reprocess_service import reprocess_document",
    )
    replace_exact(
        documents_router,
        "from server import classify_document",
        "from services.document_handlers import classify_document",
    )
    replace_exact(
        readiness_router,
        "from server import _reprocess_document_inner",
        (
            "from services.document_reprocess_service import "
            "reprocess_document_inner as _reprocess_document_inner"
        ),
    )

    replace_exact(
        handlers,
        """            # Orchestration Extraction (v2.5.2) — compute_ap_normalized_fields
            # is directly imported from document_intel_helpers (the server.py
            # version is already a thin wrapper). _update_standard_workflow_status
            # remains in server.py for this iteration (next extraction pass).
            from server import _update_standard_workflow_status
            from services.document_intel_helpers import compute_ap_normalized_fields
            norm_fields = compute_ap_normalized_fields(extracted_fields)
            await _update_standard_workflow_status(doc_id, doc_type_value, confidence, norm_fields)
""",
        """            from services.document_intel_helpers import compute_ap_normalized_fields
            from workflows.document_capture.rules.workflow_status import (
                update_standard_workflow_status,
            )
            norm_fields = compute_ap_normalized_fields(extracted_fields)
            await update_standard_workflow_status(
                doc_id, doc_type_value, confidence, norm_fields
            )
""",
    )

    replace_function(
        server,
        "reprocess_document",
        '''async def reprocess_document(doc_id: str, reclassify: bool = Query(False)):
    """Compatibility wrapper for services.document_reprocess_service."""
    from services.document_reprocess_service import reprocess_document as _impl
    return await _impl(doc_id, reclassify=reclassify)''',
    )
    replace_function(
        server,
        "_reprocess_document_inner",
        '''async def _reprocess_document_inner(doc_id: str, doc: dict, reclassify: bool):
    """Compatibility wrapper for services.document_reprocess_service."""
    from services.document_reprocess_service import reprocess_document_inner
    return await reprocess_document_inner(doc_id, doc, reclassify)''',
    )

    print("document reprocess extraction applied")


if __name__ == "__main__":
    main()
