"""One-time exact AL patch for Posted Sales Shipment Hub entity mapping."""

from pathlib import Path

path = Path("bc-extension/src/codeunit/GPIDocumentLinkMgt.Codeunit.al")
text = path.read_text(encoding="utf-8")

old = '''            "GPI Doc Link Type"::"Purchase Order":\n                exit('purchaseOrders');\n            "GPI Doc Link Type"::"Sales Order",\n'''
new = '''            "GPI Doc Link Type"::"Purchase Order":\n                exit('purchaseOrders');\n            "GPI Doc Link Type"::"Posted Sales Shipment":\n                exit('postedSalesShipments');\n            "GPI Doc Link Type"::"Sales Order",\n'''

if text.count(old) != 1:
    raise SystemExit(f"Posted shipment entity mapping insertion: expected 1 match, found {text.count(old)}")

text = text.replace(old, new, 1)
if "exit('postedSalesShipments');" not in text:
    raise SystemExit("Posted shipment entity mapping missing after patch")

path.write_text(text, encoding="utf-8")
print("PASS: Posted Sales Shipment entity mapping applied")

# trigger: workflow exists on branch
