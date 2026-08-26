from pathlib import Path
import re


BACKEND = Path(__file__).resolve().parents[1]

# During AP/Warehouse parity these are the only files permitted to contain an
# executable call to BusinessCentralService.create_sales_order(). Both are
# independently disabled by the HTTP/startup scope barriers.
ALLOWED_CREATE_SALES_ORDER_CALLERS = {
    "routers/bc_sandbox.py",
    "services/auto_post_service.py",
}


def test_create_sales_order_callsites_are_quarantined():
    callers = set()
    pattern = re.compile(r"\b(?:bc_service|service)\.create_sales_order\s*\(")

    for path in BACKEND.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            callers.add(path.relative_to(BACKEND).as_posix())

    assert callers <= ALLOWED_CREATE_SALES_ORDER_CALLERS, (
        "Unquarantined Sales-order write caller(s): "
        f"{sorted(callers - ALLOWED_CREATE_SALES_ORDER_CALLERS)}"
    )
    assert "routers/bc_sandbox.py" in callers
    assert "services/auto_post_service.py" in callers


def test_known_sales_write_callers_have_independent_kill_switches():
    scope = (BACKEND / "services/parity_scope_guard.py").read_text(encoding="utf-8")
    startup = (BACKEND / "services/startup_validator.py").read_text(encoding="utf-8")

    assert "/api/bc/sales-orders/create" in scope
    assert "AUTO_CREATE_SALES_ORDER_ENABLED" in startup
    assert "ENABLE_OUT_OF_SCOPE_SALES_ROUTES" in startup
