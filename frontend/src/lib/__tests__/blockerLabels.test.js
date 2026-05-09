import { labelForBlocker, labelForWarning } from "../blockerLabels";

describe("labelForBlocker", () => {
  test("returns mapped label for a known blocker code", () => {
    expect(labelForBlocker("po_missing")).toBe("PO missing");
  });

  test("title-cases an unknown snake_case code", () => {
    expect(labelForBlocker("some_unknown_code")).toBe("Some Unknown Code");
  });

  test("maps the AP-readiness raw codes to plain English", () => {
    expect(labelForBlocker("vendor_match")).toBe("Vendor match failed");
    expect(labelForBlocker("po_validation")).toBe("PO validation failed");
    expect(labelForBlocker("po_missing")).toBe("PO missing");
  });

  test("returns empty string for nullish input", () => {
    expect(labelForBlocker(null)).toBe("");
    expect(labelForBlocker(undefined)).toBe("");
    expect(labelForBlocker("")).toBe("");
  });
});

describe("labelForWarning", () => {
  test("returns empty string for null / undefined", () => {
    expect(labelForWarning(null)).toBe("");
    expect(labelForWarning(undefined)).toBe("");
  });

  test("delegates string warnings to labelForBlocker", () => {
    expect(labelForWarning("po_missing")).toBe("PO missing");
  });

  test("renders freight_direction_unknown object as plain English (not JSON)", () => {
    const warn = {
      check_name: "freight_direction_unknown",
      details:
        "Order reference 'X' not found as Sales Order or Purchase Order - cannot determine freight direction",
    };
    const out = labelForWarning(warn);
    expect(out).toContain("Could not determine if this freight invoice");
    expect(out).toContain("Order reference 'X'");
    // Critical: never a JSON-stringified blob.
    expect(out).not.toMatch(/^\{/);
    expect(out).not.toContain('"check_name"');
    expect(out).not.toContain("'check_name'");
  });

  test("prefers .message when present on the warning object", () => {
    expect(
      labelForWarning({ message: "Custom UI-ready message" })
    ).toBe("Custom UI-ready message");
  });

  test("falls back to .details when no check_name and no message", () => {
    expect(labelForWarning({ details: "Something happened" })).toBe(
      "Something happened"
    );
  });

  test("unknown object warning never returns JSON.stringify output", () => {
    const warn = { foo: "bar", baz: 42 };
    const out = labelForWarning(warn);
    expect(out).toBe("Warning");
    expect(out).not.toContain("{");
    expect(out).not.toContain('"foo"');
  });

  test("title-cases an unknown check_name rather than dumping JSON", () => {
    const out = labelForWarning({ check_name: "some_new_warning_code" });
    expect(out).toBe("Some New Warning Code");
    expect(out).not.toContain("{");
  });

  test("vendor_unmatched / amount_missing / invoice_date_missing have human labels", () => {
    expect(labelForWarning({ check_name: "vendor_unmatched" })).toBe(
      "Vendor not matched to a Business Central record yet"
    );
    expect(labelForWarning({ check_name: "amount_missing" })).toBe(
      "Total amount is missing"
    );
    expect(labelForWarning({ check_name: "invoice_date_missing" })).toBe(
      "Invoice date is missing"
    );
  });

  test("non-object non-string returns the literal 'Warning' fallback", () => {
    expect(labelForWarning(42)).toBe("Warning");
    expect(labelForWarning(true)).toBe("Warning");
  });
});
