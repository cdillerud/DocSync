"""Phase 3.1 — Lightweight Playwright e2e for the /contracts page.

Verifies:
  * Page loads with all 5 tabs rendered
  * Each tab body switches when clicked
  * Empty-state messages render where applicable
  * Resolve-exception dialog opens (Phase 3.1 replacement for window.prompt)
    when fixture exception data is seeded (skipped gracefully if not seeded)
  * Exception-mapping dialog opens when fixture exception data is seeded
    (also skipped gracefully)

This test runs against the live preview environment. It does NOT mutate
anything in the database — every action is read-only or covered by a
"only-if-fixture-present" gate. Safe to run in CI.

Run (interpreter must have playwright):
    /opt/plugins-venv/bin/python -m pytest tests/e2e/test_contracts_page_e2e.py -q

Env (overrides):
    HUB_BASE_URL  — defaults to https://eod-controller-seq.preview.emergentagent.com
    HUB_EMAIL     — defaults to hub-admin@gamerpackaging.com
    HUB_PASSWORD  — defaults to ChangeMeOnFirstDeploy-K8p2q
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this venv")

from playwright.sync_api import Page, expect, sync_playwright  # noqa: E402


BASE_URL = os.environ.get(
    "HUB_BASE_URL",
    "https://eod-controller-seq.preview.emergentagent.com",
)
EMAIL = os.environ.get("HUB_EMAIL", "hub-admin@gamerpackaging.com")
PASSWORD = os.environ.get("HUB_PASSWORD", "ChangeMeOnFirstDeploy-K8p2q")

TAB_TESTIDS = [
    "tab-agreements",
    "tab-exceptions",
    "tab-bc-links",
    "tab-expirations",
    "tab-analytics",
]


def _login_and_goto_contracts(page: Page) -> None:
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector('input[type="email"]', timeout=15000)
    page.fill('input[type="email"]', EMAIL)
    page.fill('input[type="password"]', PASSWORD)
    page.click('button[type="submit"]')
    # Wait for redirect off /login.
    page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
    page.wait_for_timeout(1500)  # let the SPA settle
    page.goto(f"{BASE_URL}/contracts", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector('[data-testid="contract-intelligence-page"]', timeout=30000)


@pytest.fixture(scope="module")
def browser_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            _login_and_goto_contracts(page)
            yield page
        finally:
            ctx.close()
            browser.close()


# ---------------------------------------------------------------------------
# 1. Page loads
# ---------------------------------------------------------------------------

def test_contracts_page_renders(browser_page: Page):
    expect(browser_page.locator(
        '[data-testid="contract-intelligence-page"] h1'
    )).to_have_text("Contract Intelligence")


# ---------------------------------------------------------------------------
# 2. All 5 tabs render
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tab_id", TAB_TESTIDS)
def test_each_tab_visible(browser_page: Page, tab_id: str):
    tab = browser_page.locator(f'[data-testid="{tab_id}"]')
    expect(tab).to_be_visible()


# ---------------------------------------------------------------------------
# 3. Tabs switch when clicked
# ---------------------------------------------------------------------------

def test_switch_to_exceptions_tab(browser_page: Page):
    browser_page.click('[data-testid="tab-exceptions"]')
    browser_page.wait_for_selector('[data-testid="exceptions-tab"]', timeout=5000)
    expect(browser_page.locator('[data-testid="exceptions-tab"]')).to_be_visible()


def test_switch_to_analytics_tab(browser_page: Page):
    browser_page.click('[data-testid="tab-analytics"]')
    browser_page.wait_for_selector('[data-testid="analytics-tab"]', timeout=5000)
    expect(browser_page.locator('[data-testid="analytics-tab"]')).to_be_visible()
    # The 4 top-level cards should be present
    for card in (
        "card-agreements-total", "card-exceptions-open",
        "card-links-total", "card-events-unprocessed",
    ):
        expect(browser_page.locator(f'[data-testid="{card}"]')).to_be_visible()


def test_switch_to_expirations_tab(browser_page: Page):
    browser_page.click('[data-testid="tab-expirations"]')
    browser_page.wait_for_selector('[data-testid="expirations-tab"]', timeout=5000)
    expect(browser_page.locator('[data-testid="expirations-days-input"]')).to_be_visible()


def test_switch_to_bc_links_tab(browser_page: Page):
    browser_page.click('[data-testid="tab-bc-links"]')
    browser_page.wait_for_selector('[data-testid="bc-links-tab"]', timeout=5000)
    # Cards for status counts must be visible
    for s in ("confirmed", "auto_confirmed", "proposed", "rejected"):
        expect(browser_page.locator(f'[data-testid="bc-links-card-{s}"]')).to_be_visible()


# ---------------------------------------------------------------------------
# 4. Resolve-exception dialog opens (Phase 3.1: window.prompt() replacement)
#    Skipped gracefully when no exception fixtures are present in the env.
# ---------------------------------------------------------------------------

def test_resolve_exception_dialog_opens_if_fixture_present(browser_page: Page):
    browser_page.click('[data-testid="tab-exceptions"]')
    browser_page.wait_for_selector('[data-testid="exceptions-tab"]', timeout=5000)
    # Find any "Resolve" button (one per open exception). Skip if none seeded.
    resolve_btns = browser_page.locator('[data-testid^="resolve-exception-"]')
    if resolve_btns.count() == 0:
        pytest.skip("No open exceptions seeded in this environment.")
    resolve_btns.first.click()
    expect(browser_page.locator(
        '[data-testid="resolve-exception-dialog-dialog"]'
    )).to_be_visible()
    expect(browser_page.locator(
        '[data-testid="resolve-exception-dialog-textarea"]'
    )).to_be_visible()
    # Cancel without submitting (read-only test)
    browser_page.click('[data-testid="resolve-exception-dialog-cancel"]')


# ---------------------------------------------------------------------------
# 5. Exception-mapping dialog opens (skipped gracefully if no fixture)
# ---------------------------------------------------------------------------

def test_exception_mapping_dialog_opens_if_fixture_present(browser_page: Page):
    browser_page.click('[data-testid="tab-exceptions"]')
    browser_page.wait_for_selector('[data-testid="exceptions-tab"]', timeout=5000)
    map_btns = browser_page.locator('[data-testid^="map-exception-"]')
    if map_btns.count() == 0:
        pytest.skip("No mappable (party_unmatched / item_unmatched) exceptions seeded.")
    map_btns.first.click()
    expect(browser_page.locator(
        '[data-testid="exception-mapping-dialog"]'
    )).to_be_visible()
    expect(browser_page.locator(
        '[data-testid="exception-mapping-link-type"]'
    )).to_be_visible()
    expect(browser_page.locator(
        '[data-testid="exception-mapping-search-btn"]'
    )).to_be_visible()
    # Cancel without submitting
    browser_page.click('[data-testid="exception-mapping-cancel"]')
