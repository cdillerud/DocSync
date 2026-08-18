from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Streamlit executes this file as a script. Ensure the repository root is importable
# so package imports work reliably when launched from the repo root or another folder.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from poc.commercial_guardrails.supplier_cockpit_core import (
    DECISION_OPTIONS,
    detail_rows_for_item,
    filter_records,
    load_csv_records,
    records_to_csv,
    summarize_queue,
    validate_decisions,
    write_decision_csv,
)


DEFAULT_QUEUE = "poc/commercial_guardrails/live_supplier_approval_queue.csv"
DEFAULT_DETAIL = "poc/commercial_guardrails/live_supplier_margin_impact.csv"
DEFAULT_DECISIONS = "poc/commercial_guardrails/live_supplier_approval_decisions.csv"


def _money(value: object) -> str:
    try:
        return f"${float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _pct(value: object) -> str:
    try:
        return f"{float(value or 0):.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def _normalize_editor_result(value) -> list[dict]:
    if isinstance(value, list):
        return [dict(row) for row in value]
    if isinstance(value, dict):
        keys = list(value.keys())
        if keys and all(isinstance(value[key], dict) for key in keys):
            row_ids = []
            for key in keys:
                row_ids.extend(value[key].keys())
            unique_ids = list(dict.fromkeys(row_ids))
            return [
                {column: value[column].get(row_id, "") for column in keys}
                for row_id in unique_ids
            ]
        return [dict(value)]
    if hasattr(value, "to_dict"):
        try:
            return [dict(row) for row in value.to_dict(orient="records")]
        except TypeError:
            pass
    return []


def main() -> None:
    st.set_page_config(page_title="GPI Supplier Cost Cockpit", layout="wide")
    st.title("GPI Commercial Guardrail")
    st.caption("Supplier Cost Review Cockpit | local review only | no Business Central writes")

    with st.sidebar:
        st.header("Data")
        queue_path = st.text_input("Approval queue CSV", value=DEFAULT_QUEUE)
        detail_path = st.text_input("Margin impact detail CSV", value=DEFAULT_DETAIL)
        decision_path = st.text_input("Decision output CSV", value=DEFAULT_DECISIONS)
        st.caption("The cockpit reads local CSV files produced by the validated POC pipeline.")

    queue_records = load_csv_records(queue_path)
    if not queue_records:
        st.warning(
            "No approval queue rows were found. Run bc_supplier_approval_queue_cli first or select a queue CSV in the sidebar."
        )
        return

    detail_records = load_csv_records(detail_path)
    summary = summarize_queue(queue_records)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Approval items", int(summary["items"]))
    col2.metric("Protected items", int(summary["protected_items"]))
    col3.metric("Affected customers", int(summary["affected_customers"]))
    col4.metric("Protected customers", int(summary["protected_customers"]))
    col5.metric("Actionable erosion", _money(summary["estimated_margin_erosion"]))

    st.subheader("Queue")
    statuses = sorted({str(row.get("queue_status") or "") for row in queue_records if row.get("queue_status")})
    f1, f2, f3 = st.columns([2, 2, 3])
    selected_statuses = f1.multiselect("Status", statuses, default=statuses)
    supplier_filter = f2.text_input("Supplier contains")
    item_filter = f3.text_input("GPI item contains")

    filtered = filter_records(
        queue_records,
        statuses=selected_statuses,
        supplier_text=supplier_filter,
        item_text=item_filter,
    )

    if not filtered:
        st.info("No queue rows match the current filters.")
        return

    for row in filtered:
        row.setdefault("decision", "")
        row.setdefault("decision_by", "")
        row.setdefault("decision_notes", "")

    all_columns = list(filtered[0].keys())
    editable = {"decision", "decision_by", "decision_notes"}
    disabled_columns = [column for column in all_columns if column not in editable]
    preferred_order = [
        "queue_status",
        "supplier_name",
        "gpi_item_no",
        "effective_date",
        "supplier_current_cost",
        "supplier_new_cost",
        "supplier_cost_delta_pct",
        "affected_customers",
        "estimated_margin_erosion",
        "min_projected_gp_pct",
        "top_customer_no",
        "action",
        "decision",
        "decision_by",
        "decision_notes",
    ]
    column_order = [column for column in preferred_order if column in all_columns]

    edited = st.data_editor(
        filtered,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        disabled=disabled_columns,
        column_order=column_order,
        column_config={
            "decision": st.column_config.SelectboxColumn(
                "Decision",
                options=list(DECISION_OPTIONS),
                required=False,
            ),
            "decision_by": st.column_config.TextColumn("Decision By"),
            "decision_notes": st.column_config.TextColumn("Decision Notes", width="large"),
            "estimated_margin_erosion": st.column_config.NumberColumn(
                "Est. Erosion", format="$%.2f"
            ),
            "supplier_current_cost": st.column_config.NumberColumn(
                "Current Cost", format="$%.4f"
            ),
            "supplier_new_cost": st.column_config.NumberColumn(
                "Proposed Cost", format="$%.4f"
            ),
            "supplier_cost_delta_pct": st.column_config.NumberColumn(
                "Cost Change %", format="%.1f%%"
            ),
            "min_projected_gp_pct": st.column_config.NumberColumn(
                "Lowest Projected GP", format="%.1f%%"
            ),
        },
        key="supplier_queue_editor",
    )
    edited_records = _normalize_editor_result(edited)

    errors = validate_decisions(edited_records)
    if errors:
        st.error("Decision validation: " + " | ".join(errors))

    save_col, download_col, spacer = st.columns([1, 1, 4])
    if save_col.button("Save decisions locally", type="primary", disabled=bool(errors)):
        try:
            write_decision_csv(edited_records, decision_path)
        except (OSError, ValueError) as exc:
            st.error(str(exc))
        else:
            st.success(f"Saved: {Path(decision_path).resolve()}")

    download_col.download_button(
        "Download decisions CSV",
        data=records_to_csv(edited_records),
        file_name=Path(decision_path).name,
        mime="text/csv",
        disabled=bool(errors),
    )

    st.divider()
    st.subheader("Item review")
    item_options = [str(row.get("gpi_item_no") or "") for row in filtered]
    selected_item = st.selectbox("Review item", item_options)
    selected = next(
        row for row in filtered if str(row.get("gpi_item_no") or "") == selected_item
    )

    a, b, c, d = st.columns(4)
    a.metric("Supplier change", _pct(selected.get("supplier_cost_delta_pct")))
    b.metric("Trailing sales", _money(selected.get("trailing_sales")))
    c.metric("Est. margin erosion", _money(selected.get("estimated_margin_erosion")))
    d.metric("Lowest projected GP", _pct(selected.get("min_projected_gp_pct")))

    st.write(f"**Status:** {selected.get('queue_status', '')}")
    st.write(f"**Action:** {selected.get('action', '')}")
    st.write(
        "**Cost:** "
        f"{_money(selected.get('supplier_current_cost'))}/{selected.get('uom', '')} to "
        f"{_money(selected.get('supplier_new_cost'))}/{selected.get('uom', '')}"
    )
    st.write(
        f"**Top exposure:** {selected.get('top_customer_no', '')} / "
        f"{_money(selected.get('top_customer_erosion'))}"
    )
    if str(selected.get("pricing_approvers") or "").strip():
        st.write(f"**Pricing approver:** {selected.get('pricing_approvers')}")

    customer_rows = detail_rows_for_item(detail_records, selected_item)
    if customer_rows:
        st.markdown("#### Customer margin impact")
        customer_columns = [
            "customer_no",
            "customer_name",
            "sales_rep",
            "history_lines",
            "last_sale",
            "recent_sell_median",
            "recent_cost_median",
            "projected_cost",
            "current_gp_pct",
            "projected_gp_pct",
            "gp_drop_points",
            "trailing_quantity",
            "estimated_margin_erosion",
            "special_pricing_protected",
            "pricing_approvers",
        ]
        visible = [
            {key: row.get(key, "") for key in customer_columns if key in row}
            for row in customer_rows
        ]
        st.dataframe(visible, width="stretch", hide_index=True)
    else:
        st.info(
            "No customer-detail rows were found for this item. The queue remains usable; generate the margin-impact CSV to add customer drill-down."
        )

    st.divider()
    st.caption(
        "Safety: APPROVE is blocked for PROTECTED_REVIEW rows. Saving here writes only a local decision CSV. It does not update Business Central."
    )


if __name__ == "__main__":
    main()
