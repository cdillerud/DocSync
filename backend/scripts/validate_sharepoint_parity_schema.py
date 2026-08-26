#!/usr/bin/env python3
"""Validate the configured SharePoint library's Square9 parity metadata schema.

Read-only diagnostic. It performs Graph GET requests only and exits nonzero when
required internal columns are missing or incompatible.
"""

import asyncio
import json
import sys
from pathlib import Path

# Allow execution from either repository root or backend/.
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.sharepoint_parity_schema_service import validate_live_sharepoint_parity_schema


async def main() -> int:
    try:
        result = await validate_live_sharepoint_parity_schema()
    except Exception as exc:
        print(json.dumps({"ready": False, "error": str(exc)}, indent=2))
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ready") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
