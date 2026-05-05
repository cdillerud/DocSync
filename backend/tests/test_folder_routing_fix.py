"""
Test folder routing fixes for 4 misrouted bakeoff documents.
"""
import sys
sys.path.insert(0, "/app/backend")

from services.folder_routing_service import determine_folder_path, _is_warehouse_order, _is_credit_memo


def test_sh_invoice_routes_to_sh_folder():
    """S&H_Invoice should route to S&H Invoices Approved Documents."""
    doc = {
        "file_name": "SH_112701_Warehouse_031192026.pdf",
        "document_type": "S&H_Invoice",
        "vendor_canonical": "GAMER PACKAGING WAREHOUSE",
        "extracted_fields": {},
    }
    folder, reason, details = determine_folder_path(doc)
    assert "S&H" in folder, f"S&H_Invoice should route to S&H folder, got: {folder}"
    print(f"PASS: S&H_Invoice -> {folder}")


def test_wh_international_routes_to_warehouse():
    """WH_ prefix international doc should route to Warehouse International."""
    doc = {
        "file_name": "WH_112411_Fevisa_ML180102_031192026.pdf",
        "document_type": "AP_Invoice",
        "vendor_canonical": "FEVISA INDUSTRIAL S.A. DE C.V.",
        "extracted_fields": {"order_number": "ML180102"},
    }
    assert _is_warehouse_order(doc), "WH_ file should be detected as warehouse order"
    folder, reason, details = determine_folder_path(doc)
    assert "Warehouse" in folder and "International" in folder, f"WH_ intl doc should route to Warehouse International, got: {folder}"
    print(f"PASS: WH_ international -> {folder}")


def test_wh_domestic_routes_to_warehouse():
    """WH_ prefix domestic doc should route to Warehouse Not International."""
    doc = {
        "file_name": "WH_112320_Ball_PO88701_031192026.pdf",
        "document_type": "AP_Invoice",
        "vendor_canonical": "BALL CORPORATION",
        "extracted_fields": {"order_number": "PO88701"},
    }
    assert _is_warehouse_order(doc), "WH_ file should be detected as warehouse order"
    folder, reason, details = determine_folder_path(doc)
    assert "Warehouse" in folder and "Not International" in folder, f"WH_ domestic doc should route to Warehouse Not International, got: {folder}"
    print(f"PASS: WH_ domestic -> {folder}")


def test_wh_domestic_gts_routes_to_warehouse():
    """WH_ prefix GT's doc should route to Warehouse Not International."""
    doc = {
        "file_name": "WH_112321_GTs_PO88702_031192026.pdf",
        "document_type": "AP_Invoice",
        "vendor_canonical": "GT'S LIVING FOODS",
        "extracted_fields": {"order_number": "PO88702"},
    }
    assert _is_warehouse_order(doc), "WH_ file should be detected as warehouse order"
    folder, reason, details = determine_folder_path(doc)
    assert "Warehouse" in folder, f"WH_ domestic doc should route to Warehouse, got: {folder}"
    print(f"PASS: WH_ GT's -> {folder}")


def test_credit_memo_detected():
    """Credit_Memo doc_type should be recognized."""
    assert _is_credit_memo("Credit_Memo", ""), "Credit_Memo doc_type should be recognized"
    assert _is_credit_memo("credit_memo", ""), "credit_memo doc_type should be recognized"
    assert _is_credit_memo("Return_Request", ""), "Return_Request should still work"
    print("PASS: Credit_Memo detection")


if __name__ == "__main__":
    test_sh_invoice_routes_to_sh_folder()
    test_wh_international_routes_to_warehouse()
    test_wh_domestic_routes_to_warehouse()
    test_wh_domestic_gts_routes_to_warehouse()
    test_credit_memo_detected()
    print("\nAll folder routing tests PASSED!")
