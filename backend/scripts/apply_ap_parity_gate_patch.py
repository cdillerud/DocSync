"""One-time exact patch: add AP true-post/identity coverage to permanent parity gate."""

from pathlib import Path

path = Path(".github/workflows/square9-parity-gate.yml")
text = path.read_text(encoding="utf-8")

replacements = [
    (
        "      - 'backend/services/gpi_integration_service.py'\n",
        "      - 'backend/services/gpi_integration_service.py'\n"
        "      - 'backend/services/ap_auto_post_service.py'\n"
        "      - 'backend/services/bc_purchase_invoice_posting_service.py'\n"
        "      - 'backend/services/ap_purchase_invoice_identity_service.py'\n",
        "AP service paths",
    ),
    (
        "      - 'backend/tests/test_square9_parity_metadata.py'\n",
        "      - 'backend/tests/test_square9_parity_metadata.py'\n"
        "      - 'backend/tests/test_bc_purchase_invoice_posting_service.py'\n"
        "      - 'backend/tests/test_ap_purchase_invoice_identity_service.py'\n",
        "AP test paths",
    ),
    (
        "            tests/test_square9_parity_metadata.py \\\n",
        "            tests/test_square9_parity_metadata.py \\\n"
        "            tests/test_bc_purchase_invoice_posting_service.py \\\n"
        "            tests/test_ap_purchase_invoice_identity_service.py \\\n",
        "AP pytest list",
    ),
]

for old, new, label in replacements:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected 1 match, found {text.count(old)}")
    text = text.replace(old, new, 1)

anchor = "      - name: Guardrail - BC FactBox uses deployed Hub proxy URL\n"
guard = '''      - name: Guardrail - AP Posted means true BC post action\n        run: |\n          grep -q 'post_purchase_invoice_system_id(bc_system_id)' backend/services/ap_auto_post_service.py || {\n            echo "::error::AP auto-post can report Posted without the BC bound post action"\n            exit 1\n          }\n          grep -q 'Microsoft.NAV.post' backend/services/bc_purchase_invoice_posting_service.py || {\n            echo "::error::True BC purchase-invoice post action missing"\n            exit 1\n          }\n          grep -q 'bc_true_post_confirmed' backend/services/ap_auto_post_service.py || {\n            echo "::error::AP posting audit lacks explicit true-post confirmation"\n            exit 1\n          }\n\n      - name: Guardrail - AP Purchase Invoice identity is promoted for FactBox visibility\n        run: |\n          grep -q 'build_ap_purchase_invoice_identity_update' backend/routers/gpi_integration.py || {\n            echo "::error::Draft Purchase Invoice creation does not promote top-level FactBox identity"\n            exit 1\n          }\n          grep -q '\*\*posted_identity' backend/services/ap_auto_post_service.py || {\n            echo "::error::Posted Purchase Invoice does not promote posted identity"\n            exit 1\n          }\n          grep -q '"bc_entity": "purchaseInvoices"' backend/services/ap_purchase_invoice_identity_service.py || {\n            echo "::error::AP identity handoff targets the wrong Hub entity"\n            exit 1\n          }\n\n      - name: Guardrail - ambiguous AP post responses recover read-only, never by recreation\n        run: |\n          grep -q '_verify_posted_by_pdf' backend/services/bc_purchase_invoice_posting_service.py || {\n            echo "::error::AP post boundary cannot recover from lost successful responses"\n            exit 1\n          }\n          grep -q '/pdfDocument' backend/services/bc_purchase_invoice_posting_service.py || {\n            echo "::error::AP post recovery lacks posted-state verification"\n            exit 1\n          }\n\n'''
if text.count(anchor) != 1:
    raise SystemExit(f"guard anchor: expected 1 match, found {text.count(anchor)}")
text = text.replace(anchor, guard + anchor, 1)

path.write_text(text, encoding="utf-8")
print("PASS: permanent parity gate now covers AP true-post + identity")
