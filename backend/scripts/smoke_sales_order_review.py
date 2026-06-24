"""Smoke-test the isolated sales-order review API without BC writes."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(
    base_url: str,
    method: str,
    path: str,
    payload: Dict[str, Any] | None = None,
) -> Tuple[int, Dict[str, Any]]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body or "{}")
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body or "{}")
    except URLError as exc:
        raise RuntimeError(f"Request failed for {path}: {exc}") from exc


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="http://localhost:8001",
    )
    args = parser.parse_args()
    base_url = args.base_url

    status_code, health = request_json(base_url, "GET", "/api/health")
    require(status_code == 200, f"Health failed: {status_code} {health}")
    print("PASS health")

    status_code, mode = request_json(
        base_url,
        "GET",
        "/api/sales/order-intake/status",
    )
    require(status_code == 200, f"Status failed: {status_code} {mode}")
    require(mode.get("mode") == "shadow", f"Expected shadow mode: {mode}")
    require(mode.get("write_enabled") is False, f"Writes enabled: {mode}")
    print("PASS shadow-mode safety")

    status_code, batch = request_json(
        base_url,
        "POST",
        "/api/sales/order-intake/preflight-pending?limit=100",
    )
    require(status_code == 200, f"Batch preflight failed: {batch}")
    require(batch.get("evaluated", 0) >= 9, f"Unexpected batch: {batch}")
    require(batch.get("blocked", 0) >= 1, f"No blocked cases: {batch}")
    print(
        "PASS batch preflight "
        f"({batch.get('ready')} ready, {batch.get('blocked')} blocked)"
    )

    status_code, queue = request_json(
        base_url,
        "GET",
        "/api/sales/order-intake/review?limit=100&refresh_missing=true",
    )
    require(status_code == 200, f"Review queue failed: {queue}")
    documents = queue.get("documents") or []
    ids = {document.get("document_id") for document in documents}
    require("so-approved-001" in ids, f"Ready document missing: {ids}")
    require("so-unmapped-item" in ids, f"Blocked document missing: {ids}")
    print(f"PASS review queue ({len(documents)} documents)")

    status_code, approved = request_json(
        base_url,
        "POST",
        "/api/sales/order-intake/so-approve-001/approve",
        {
            "reviewer": "Isolated Smoke Test",
            "note": "Verified by deterministic smoke test.",
        },
    )
    require(status_code == 200, f"Approve failed: {approved}")
    require(approved.get("can_create") is True, f"Approval not ready: {approved}")
    print("PASS approval and preflight rerun")

    status_code, create_result = request_json(
        base_url,
        "POST",
        "/api/sales/order-intake/so-approve-001/create-draft",
    )
    require(status_code == 409, f"Expected write block: {create_result}")
    detail = create_result.get("detail") or {}
    require(detail.get("status") == "shadow_mode", f"Unexpected block: {detail}")
    require(detail.get("success") is False, f"Unexpected success: {detail}")
    print("PASS create-draft blocked in shadow mode")

    status_code, rejected = request_json(
        base_url,
        "POST",
        "/api/sales/order-intake/so-reject-001/reject",
        {
            "reviewer": "Isolated Smoke Test",
            "reason": "Intentional smoke-test rejection.",
        },
    )
    require(status_code == 200, f"Reject failed: {rejected}")
    require(rejected.get("can_create") is False, f"Rejected order ready: {rejected}")
    error_codes = {
        issue.get("code") for issue in (rejected.get("errors") or [])
    }
    require(
        "REVIEW_APPROVAL_REQUIRED" in error_codes,
        f"Approval error missing after rejection: {rejected}",
    )
    print("PASS rejection persistence")

    status_code, unmapped = request_json(
        base_url,
        "POST",
        "/api/sales/order-intake/so-unmapped-item/preflight",
    )
    require(status_code == 200, f"Unmapped preflight failed: {unmapped}")
    error_codes = {
        issue.get("code") for issue in (unmapped.get("errors") or [])
    }
    require("ITEM_NOT_RESOLVED" in error_codes, f"Item error missing: {unmapped}")
    require(
        "ITEM_MAPPING_NOT_APPROVED" in error_codes,
        f"Mapping error missing: {unmapped}",
    )
    print("PASS unmapped-item blocking")

    print("All isolated sales-order smoke tests passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, RuntimeError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        sys.exit(1)
