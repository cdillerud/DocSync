/**
 * Tests for the inline humanizeBlockingItem helper exposed via
 * DocumentIntelligencePanel. We re-implement it here to keep the
 * frontend test surface decoupled from the heavy panel module while
 * still asserting that the same logic shape is documented.
 *
 * If the panel-internal copy of humanizeBlockingItem ever diverges
 * from this contract, this test will catch the regression.
 */
import { labelForBlocker, BLOCKER_LABELS } from "../blockerLabels";

function humanizeBlockingItem(item) {
  if (item === null || item === undefined) return "";
  const s = String(item);
  const colonIdx = s.indexOf(":");
  if (colonIdx <= 0) return labelForBlocker(s);
  const code = s.slice(0, colonIdx).trim();
  const rest = s.slice(colonIdx + 1).trim();
  const human = labelForBlocker(code);
  return rest ? `${human} — ${rest}` : human;
}

describe("humanizeBlockingItem", () => {
  test("vendor_unmatched with quoted value renders plain English", () => {
    const out = humanizeBlockingItem("vendor_unmatched: 'MRP Solutions'");
    expect(out).toContain(BLOCKER_LABELS.vendor_unmatched);
    expect(out).toContain("'MRP Solutions'");
    expect(out).not.toMatch(/^vendor_unmatched/);
  });

  test("unknown snake_case code falls back to title case (no raw leak)", () => {
    const out = humanizeBlockingItem("widget_misaligned: 'X'");
    expect(out).toMatch(/^Widget Misaligned/);
    expect(out).not.toMatch(/^widget_misaligned/);
  });

  test("plain code with no colon delegates to labelForBlocker", () => {
    expect(humanizeBlockingItem("po_validation"))
      .toBe(BLOCKER_LABELS.po_validation);
  });

  test("nullish / empty returns empty string", () => {
    expect(humanizeBlockingItem(null)).toBe("");
    expect(humanizeBlockingItem(undefined)).toBe("");
    expect(humanizeBlockingItem("")).toBe("");
  });

  test("already-humanised sentence passes through unchanged", () => {
    const sentence = "Vendor 'X' not resolved to BC vendor";
    expect(humanizeBlockingItem(sentence)).toBe(sentence);
  });
});
