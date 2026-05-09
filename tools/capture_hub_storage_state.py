"""
capture_hub_storage_state.py
============================
Laptop-side helper that opens the Hub UI in a HEADED Playwright Chromium
session, lets the operator log in normally, and exports the resulting
authenticated session (cookies + localStorage) to a Playwright
``storage_state`` JSON file.

That JSON file can then be passed to
``backend/scripts/ap_smoke_walk_dom_check.py`` via
``--storage-state-path`` so the automated DOM checker runs as a
logged-in user — without requiring any backend auth bypass, credentials
in scripts, or SCP gymnastics.

Strict scope:
    - No backend changes.
    - No Mongo writes.
    - No data changes.
    - No Save / Mark Ready / Post.
    - No matcher / classifier / routing changes.
    - This script only opens a browser, waits for login, and writes
      a JSON file.

Usage (run on a workstation with a visible desktop):

    pip install playwright
    python -m playwright install chromium
    python tools/capture_hub_storage_state.py \
        --hub-origin http://4.204.41.190:8080 \
        --out hub_storage_state.json

After login the file is saved and the next command to run
``ap_smoke_walk_dom_check.py`` is printed to stdout.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional


DEFAULT_HUB_ORIGIN = "http://4.204.41.190:8080"
DEFAULT_OUT_PATH = "hub_storage_state.json"
DEFAULT_LOGIN_TIMEOUT_S = 300  # 5 minutes — generous for SSO redirects.


def _import_playwright_or_die() -> None:
    try:
        import playwright  # noqa: F401
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "capture_hub_storage_state: Playwright is not installed.\n"
            "    pip install playwright\n"
            "    python -m playwright install chromium\n"
        )
        raise SystemExit(127)


def _wait_for_login(page, *, timeout_s: int) -> bool:
    """Poll until the page no longer shows a password input.

    Returns True when the login form disappears, False when the timeout
    elapses. Pure read-only — no clicks issued.
    """
    import time
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        try:
            if page.locator("input[type=password]").count() == 0:
                return True
        except Exception:  # noqa: BLE001 — best-effort polling
            pass
        time.sleep(1.0)
    return False


def capture(hub_origin: str, out_path: str,
            *, login_timeout_s: int = DEFAULT_LOGIN_TIMEOUT_S) -> int:
    """Run the headed capture flow. Returns a process exit code."""
    _import_playwright_or_die()
    from playwright.sync_api import sync_playwright  # noqa: WPS433

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    print("=" * 72)
    print(" capture_hub_storage_state")
    print("=" * 72)
    print(f"  hub-origin       : {hub_origin}")
    print(f"  out              : {out_path}")
    print(f"  login timeout    : {login_timeout_s}s")
    print()
    print("  A Chromium window will open. Sign in normally.")
    print("  When the login form is gone, the session is exported.")
    print("  Nothing is clicked or saved on your behalf.")
    print()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(hub_origin, wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(
                f"capture_hub_storage_state: could not load "
                f"{hub_origin!r}: {e}\n")
            context.close()
            browser.close()
            return 4

        if not _wait_for_login(page, timeout_s=login_timeout_s):
            sys.stderr.write(
                "capture_hub_storage_state: login form still present "
                f"after {login_timeout_s}s. No state was saved.\n")
            context.close()
            browser.close()
            return 5

        context.storage_state(path=out_path)
        context.close()
        browser.close()

    if not os.path.exists(out_path):
        sys.stderr.write(
            "capture_hub_storage_state: storage state was not written. "
            "Aborting.\n")
        return 6

    abs_out = os.path.abspath(out_path)
    print()
    print("=" * 72)
    print("  Login captured.")
    print(f"    saved to: {abs_out}")
    print()
    print("  Next step — run the automated DOM checker. From the same")
    print("  machine where this file lives, with the smoke CSV nearby:")
    print()
    print("    python backend/scripts/ap_smoke_walk_dom_check.py \\")
    print(f"      --hub-origin {hub_origin} \\")
    print("      --priorities P0,P1 \\")
    print("      --input-csv prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv \\")
    print("      --out-csv prod_reports/AP_SMOKE_WALK_DOM_CHECK_RESULTS.csv \\")
    print("      --out-summary-md prod_reports/AP_SMOKE_WALK_DOM_CHECK_SUMMARY.md \\")
    print("      --screenshot-dir prod_reports/ap_smoke_walk_screens \\")
    print(f"      --storage-state-path {abs_out}")
    print()
    print("  Or, if you prefer the bundled local runner:")
    print()
    print("    python tools/run_ap_smoke_dom_check_local.py \\")
    print(f"      --hub-origin {hub_origin} \\")
    print(f"      --storage-state-path {abs_out}")
    print("=" * 72)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Capture a logged-in Playwright storage_state JSON "
                    "for the GPI Hub UI. Read-only.")
    p.add_argument("--hub-origin", default=DEFAULT_HUB_ORIGIN,
                   help=f"Default: {DEFAULT_HUB_ORIGIN}")
    p.add_argument("--out", default=DEFAULT_OUT_PATH,
                   help=f"Output JSON path. Default: {DEFAULT_OUT_PATH}")
    p.add_argument("--login-timeout-s", type=int,
                   default=DEFAULT_LOGIN_TIMEOUT_S,
                   help="How long to wait for the login form to "
                        "disappear before giving up.")
    args = p.parse_args(argv)
    return capture(args.hub_origin, args.out,
                   login_timeout_s=args.login_timeout_s)


if __name__ == "__main__":
    raise SystemExit(main())
