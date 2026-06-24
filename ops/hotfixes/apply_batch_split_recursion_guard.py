#!/usr/bin/env python3
"""Apply the batch split recursion guard to production document_handlers.py."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_TARGET = Path(
    "/opt/gpi-hub/backend/services/document_handlers.py"
)

OLD_BLOCK = '''        from services.batch_po_splitter import detect_batch_po
        batch_info = detect_batch_po(file_content, suggested_type)
'''

NEW_BLOCK = '''        from services.batch_po_splitter import detect_batch_po

        split_child_sources = {
            "auto_split",
            "batch_split",
            "manual_auto_split",
        }
        normalized_source = str(source or "").strip().lower()

        if normalized_source in split_child_sources:
            batch_info = {
                "should_split": False,
                "reason": "split_child_recursion_guard",
            }
            logger.info(
                "[INTAKE] Batch split recursion guard: doc=%s source=%s",
                doc_id[:8],
                normalized_source,
            )
        else:
            batch_info = detect_batch_po(file_content, suggested_type)
'''

MARKER = '"reason": "split_child_recursion_guard"'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="Path to production document_handlers.py",
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--check",
        action="store_true",
        help="Validate whether the patch is present or applicable.",
    )
    action.add_argument(
        "--apply",
        action="store_true",
        help="Back up and apply the patch.",
    )

    return parser.parse_args()


def validate_python(path: Path) -> None:
    source = path.read_text(
        encoding="utf-8",
        errors="strict",
    )
    compile(
        source,
        str(path),
        "exec",
    )


def main() -> int:
    args = parse_args()
    target = args.target.resolve()

    if not target.is_file():
        print(
            f"ERROR: target does not exist: {target}",
            file=sys.stderr,
        )
        return 1

    text = target.read_text(
        encoding="utf-8",
        errors="strict",
    )

    if MARKER in text:
        validate_python(target)
        print(f"OK: recursion guard is already present in {target}")
        return 0

    occurrences = text.count(OLD_BLOCK)

    if occurrences != 1:
        print(
            "ERROR: expected exactly one unguarded batch detection block, "
            f"found {occurrences}. No changes were written.",
            file=sys.stderr,
        )
        return 1

    if args.check:
        print(f"OK: recursion guard can be applied to {target}")
        return 0

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    backup = target.with_name(
        f"{target.name}.pre-recursion-guard.{timestamp}.bak"
    )

    shutil.copy2(target, backup)

    try:
        patched = text.replace(
            OLD_BLOCK,
            NEW_BLOCK,
            1,
        )
        target.write_text(
            patched,
            encoding="utf-8",
        )
        validate_python(target)
    except Exception:
        shutil.copy2(backup, target)
        print(
            f"ERROR: patch failed. Restored {backup}",
            file=sys.stderr,
        )
        raise

    print(f"OK: recursion guard applied to {target}")
    print(f"Backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
