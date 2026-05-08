"""
verify_bucket_A_apply.py
========================
READ-ONLY verifier. Prints the current values of the fields the Bucket A
one-shot data patch is responsible for, for an explicit list of doc IDs.

Usage:
  python scripts/verify_bucket_A_apply.py \\
      --ids 9391f78f-33c2-4186-9199-7df2da1124bb \\
            5fe1d5c2-275c-4bbd-a693-6073a0fe9567

Prints (per doc):
  id, file_name, email_sender, mailbox_category, doc_type,
  suggested_job_type, remediation_audit

Performs only ``find_one`` against ``hub_documents``. No writes.

Exit codes:
  0  every requested doc was found
  1  at least one requested doc was not found
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

# Same canonical ID field as the apply script.
HUB_DOC_ID_FIELD = "id"

PROJECTION_FIELDS = [
    "id",
    "file_name",
    "email_sender",
    "mailbox_category",
    "doc_type",
    "suggested_job_type",
    "remediation_audit",
]


def get_collection():
    from pymongo import MongoClient  # noqa: WPS433
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise RuntimeError("MONGO_URL / DB_NAME env vars are required.")
    return MongoClient(mongo_url)[db_name]["hub_documents"]


def project(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if doc is None:
        return {}
    return {k: doc.get(k) for k in PROJECTION_FIELDS}


def fetch_docs(collection, ids: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
    out: Dict[str, Optional[Dict[str, Any]]] = {}
    projection = {f: 1 for f in PROJECTION_FIELDS}
    projection["_id"] = 0
    for doc_id in ids:
        out[doc_id] = collection.find_one(
            {HUB_DOC_ID_FIELD: doc_id}, projection)
    return out


def render(records: Dict[str, Optional[Dict[str, Any]]]) -> str:
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append(" verify_bucket_A_apply (READ-ONLY)")
    lines.append("=" * 72)
    for doc_id, doc in records.items():
        lines.append(f"  id: {doc_id}")
        if doc is None:
            lines.append("    NOT FOUND")
            lines.append("")
            continue
        lines.append(f"    file_name           : {doc.get('file_name')}")
        lines.append(f"    email_sender        : {doc.get('email_sender')}")
        lines.append(f"    mailbox_category    : {doc.get('mailbox_category')}")
        lines.append(f"    doc_type            : {doc.get('doc_type')}")
        lines.append(f"    suggested_job_type  : {doc.get('suggested_job_type')}")
        audit = doc.get("remediation_audit")
        if isinstance(audit, dict):
            lines.append(f"    remediation_audit   :")
            for k in sorted(audit.keys()):
                v = audit[k]
                if isinstance(v, (dict, list)):
                    v_str = json.dumps(v, default=str)
                else:
                    v_str = str(v)
                if len(v_str) > 80:
                    v_str = v_str[:77] + "..."
                lines.append(f"      {k:18s} = {v_str}")
        else:
            lines.append(f"    remediation_audit   : {audit}")
        lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Verify the post-apply state of Bucket A docs.",
    )
    p.add_argument("--ids", nargs="+", required=True,
                   help="One or more hub_documents.id UUIDs to verify.")
    args = p.parse_args()
    coll = get_collection()
    records = fetch_docs(coll, args.ids)
    print(render(records))
    missing = [k for k, v in records.items() if v is None]
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
