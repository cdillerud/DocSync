#!/usr/bin/env python3
"""
GPI Document Hub - Test Script
Creates/selects a Sales Order in BC sandbox, uploads a sample PDF, and links it.
"""
import requests
import sys
import json

# Configuration
HUB_BASE_URL = "http://localhost:8001"
API = f"{HUB_BASE_URL}/api"

def main():
    print("=" * 60)
    print("GPI Document Hub - Test Script")
    print("=" * 60)

    # Step 1: Login
    print("\n[1] Logging in...")
    resp = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"    Token: {token[:20]}...")

    # Step 2: Check dashboard
    print("\n[2] Checking dashboard stats...")
    resp = requests.get(f"{API}/dashboard/stats", headers=headers)
    assert resp.status_code == 200
    stats = resp.json()
    print(f"    Total docs: {stats['total_documents']}")
    print(f"    Demo mode: {stats['demo_mode']}")

    # Step 3: List BC Sales Orders
    print("\n[3] Listing BC Sales Orders...")
    resp = requests.get(f"{API}/bc/sales-orders", headers=headers)
    assert resp.status_code == 200
    orders = resp.json()["orders"]
    print(f"    Found {len(orders)} orders")
    if orders:
        order = orders[0]
        print(f"    Using: {order['number']} - {order['customerName']}")
    else:
        print("    No orders found (this shouldn't happen in demo mode)")
        sys.exit(1)

    # Step 4: Upload a sample document
    print("\n[4] Uploading sample document...")
    # Create a simple PDF-like file for testing
    sample_content = b"%PDF-1.4 Sample test document for GPI Document Hub"
    files = {"file": ("test-invoice-001.pdf", sample_content, "application/pdf")}
    data = {
        "document_type": "SalesOrder",
        "bc_document_no": order["number"],
        "bc_record_id": order["id"],
        "source": "manual_upload"
    }
    resp = requests.post(f"{API}/documents/upload", files=files, data=data, headers=headers)
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    result = resp.json()
    doc = result["document"]
    workflow_id = result["workflow_id"]

    print(f"    Document ID: {doc['id']}")
    print(f"    Status: {doc['status']}")
    print(f"    SharePoint URL: {doc.get('sharepoint_web_url', 'N/A')}")
    print(f"    Share Link: {doc.get('sharepoint_share_link_url', 'N/A')}")
    print(f"    Workflow ID: {workflow_id}")

    # Step 5: Verify document detail
    print("\n[5] Verifying document detail...")
    resp = requests.get(f"{API}/documents/{doc['id']}", headers=headers)
    assert resp.status_code == 200
    detail = resp.json()
    print(f"    Document: {detail['document']['file_name']}")
    print(f"    Final Status: {detail['document']['status']}")
    print(f"    Workflows: {len(detail['workflows'])}")
    for wf in detail["workflows"]:
        print(f"      - {wf['workflow_name']}: {wf['status']} ({len(wf['steps'])} steps)")

    # Step 6: Check updated dashboard
    print("\n[6] Final dashboard check...")
    resp = requests.get(f"{API}/dashboard/stats", headers=headers)
    stats = resp.json()
    print(f"    Total docs: {stats['total_documents']}")
    print(f"    By status: {json.dumps(stats['by_status'], indent=6)}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE - All steps passed!")
    print("=" * 60)
    print(f"\nHub Doc ID: {doc['id']}")
    print(f"Share Link: {doc.get('sharepoint_share_link_url', 'N/A')}")

if __name__ == "__main__":
    main()
