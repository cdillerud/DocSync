"""
Daily, incremental routing learning from the Square9 parity output.

square9_continuous_learning.py re-matches the full history (tens of
thousands of Square9 files against every Hub doc), which is too heavy to
run routinely, so routing_feedback stopped learning after July. This reads
the pairs the daily readiness run already matched (prod_reports parity
CSV, exact/strong matches only) and applies the same safety rules:

  * CREATE a rule for a vendor+doc_type+has_po+is_international key with
    no rule yet; STRENGTHEN one that agrees.
  * Never overwrite a rule that disagrees, and never apply when two pairs
    in the same run disagree: record a conflict in
    routing_learning_conflicts for a person to resolve.
  * Square9's staging folder (Temp Folder) is not a filing decision.

Dry run unless --confirm APPLY. Usage (inside gpi-backend):
    PYTHONPATH=/app python scripts/square9_daily_learning.py [--csv PATH] [--confirm APPLY]
"""
import argparse
import asyncio
import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

TRUSTED = {"exact_match", "strong_evidence_match"}
NON_FINAL_FOLDERS = {"temp folder"}
MIN_AGREEING = 2            # a new rule needs this many agreeing filings in the run
JUNK_VENDORS = {"account", "unknown", "vendor", "n/a", "none"}


def _folder_root(parent_path: str) -> str:
    p = (parent_path or "").strip("/")
    return p.split("/")[0] if p else ""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="prod_reports/square9_hub_ap_parity.csv")
    ap.add_argument("--confirm", default=None, help="Pass APPLY to write rules")
    args = ap.parse_args()
    apply = args.confirm == "APPLY"

    from motor.motor_asyncio import AsyncIOMotorClient
    import deps
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    deps.set_db(db)
    from services.routing_feedback_service import record_correction, _make_routing_key, init_feedback_db  # noqa
    init_feedback_db(db)

    from services.folder_routing_service import _is_working_folder

    rows = [r for r in csv.DictReader(open(args.csv)) if r.get("match_bucket") in TRUSTED]
    created = strengthened = skipped = 0
    conflicts, proposed = [], {}
    now = datetime.now(timezone.utc).isoformat()

    # Pass 1: collect every trusted observation per routing key.
    observations = {}
    for r in rows:
        hub = await db.hub_documents.find_one(
            {"id": r.get("hub_doc_id")},
            {"_id": 0, "vendor_canonical": 1, "doc_type": 1, "po_number_clean": 1, "is_international": 1, "file_name": 1})
        vendor = ((hub or {}).get("vendor_canonical") or "").strip()
        folder = _folder_root(r.get("square9_parent_path", ""))
        if (not hub or len(vendor) < 3 or vendor.lower() in JUNK_VENDORS or not folder
                or folder.lower() in NON_FINAL_FOLDERS or not _is_working_folder(folder)):
            skipped += 1
            continue
        doc_type = (hub.get("doc_type") or "Unknown").strip()
        has_po = bool(hub.get("po_number_clean"))
        intl = bool(hub.get("is_international"))
        key = _make_routing_key(vendor, doc_type, has_po, intl)
        observations.setdefault(key, []).append((folder, vendor, doc_type, has_po, intl, hub, r))

    # Pass 2: decide per key. Disagreement in the run -> conflict; a new rule
    # needs MIN_AGREEING agreeing filings.
    for key, obs in observations.items():
        folders = {o[0].lower() for o in obs}
        folder, vendor, doc_type, has_po, intl, hub, r = obs[0]
        if len(folders) > 1:
            conflicts.append((key, sorted(folders), "(mixed within run)", r.get("square9_name", "")))
            continue

        existing = await db.routing_feedback.find_one({"routing_key": key})
        clash = None
        if existing and (existing.get("correct_folder") or "").lower() != folder.lower():
            clash = existing.get("correct_folder")
        if clash:
            conflicts.append((key, clash, folder, r.get("square9_name", "")))
            if apply:
                await db.routing_learning_conflicts.update_one(
                    {"routing_key": key},
                    {"$set": {"routing_key": key, "existing_folder": clash, "square9_folder": folder,
                              "square9_file": r.get("square9_name"), "hub_file": hub.get("file_name"),
                              "updated_at": now},
                     "$inc": {"seen": 1}},
                    upsert=True)
            continue
        if not existing and len(obs) < MIN_AGREEING:
            skipped += 1
            continue
        if apply:
            res = await record_correction(vendor=vendor, doc_type=doc_type, has_po=has_po, is_international=intl,
                                          correct_folder=folder, file_name=hub.get("file_name", ""),
                                          source="square9_daily_learning")
            if res.get("status") not in ("created", "strengthened"):
                print(f"  NOT APPLIED {key}: {res}")
                skipped += 1
                continue
        if existing:
            strengthened += 1
        else:
            created += 1
            print(f"  CREATE {key} -> {folder!r}  ({r.get('square9_name', '')[:50]})")

    print(f"\n{'APPLIED' if apply else 'DRY RUN'}: trusted pairs {len(rows)}, new rules {created}, "
          f"strengthened {strengthened}, conflicts {len(conflicts)}, skipped {skipped}")
    for key, existing, new, sqname in conflicts[:20]:
        print(f"  CONFLICT {key}: rule says {existing!r}, staff filed {new!r} ({sqname[:40]})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
