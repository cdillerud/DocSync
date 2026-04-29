"""One-shot MongoDB index initializer for the Contract Intelligence module.

Run this once per environment after pulling Phase 1 to materialize the
indexes declared in ``backend/models/contracts.py``. Idempotent — safe to
re-run after every Phase 2/3 schema iteration.

Usage (remote VM, inside docker compose):

    docker compose exec backend \
        python -m backend.scripts.contracts_init_indexes

Or inside the preview container:

    cd /app && python -m backend.scripts.contracts_init_indexes

The script does NOT touch any existing collection, only the 10 new
``agreement*`` collections. It exits non-zero if any index creation fails.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, Dict, List

# Add backend to sys.path when executed directly (`python script.py`).
import os
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from database import db  # noqa: E402  (motor singleton)
from models.contracts import (  # noqa: E402
    CONTRACTS_COLLECTIONS,
    CONTRACTS_INDEXES,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("contracts_init_indexes")


async def _ensure_collection_indexes(name: str, specs: List[Dict[str, Any]]) -> None:
    coll = db[name]
    for spec in specs:
        keys = spec["keys"]
        kwargs = {k: v for k, v in spec.items() if k != "keys"}
        try:
            created = await coll.create_index(keys, **kwargs)
            logger.info("  [%s] index ensured: %s", name, created)
        except Exception as exc:  # noqa: BLE001
            logger.error("  [%s] index FAILED (%s): %s", name, spec.get("name"), exc)
            raise


async def main() -> int:
    logger.info("Initializing Contract Intelligence indexes (%d collections)",
                len(CONTRACTS_COLLECTIONS))
    for logical, physical in CONTRACTS_COLLECTIONS.items():
        specs = CONTRACTS_INDEXES.get(logical, [])
        if not specs:
            logger.info("[%s] no indexes declared, skipping", physical)
            continue
        logger.info("[%s] ensuring %d indexes", physical, len(specs))
        await _ensure_collection_indexes(physical, specs)
    logger.info("Contract Intelligence indexes ready.")
    return 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
