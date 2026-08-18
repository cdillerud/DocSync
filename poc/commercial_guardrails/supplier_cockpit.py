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
    merge_saved_decisions,
    record_key,
    records_to_csv,
    summarize_queue,
    update_decision,
    validate_decisions,
    write_decision_csv,
)


DEFAULT_QUEUE = "poc/commercial_guardrails/live_supplier_approval_queue.csv"
DEFAULT_DETAIL = "poc/commercial_guardrails/live_supplier_margin_impact.csv"
DEFAULT_DECISIONS = "poc/commercial_guardrails/live_supplier_approval_decisions.csv"


def _float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _money(value: object) -> str:
    return f"${_float(value):,.2f}"


def _money4(value: object) -> str:
    return f"${_float(value):,.4f}"


def _pct(value: object) -> str:
    return f"{_float(value):.1f}%"


def _status_label(value: object) -> str:
    return str(value or "").strip().replace("_", " ").title()


def _file_stamp(path: str) -> tuple[str, int | None]:
    source = Path(path)
    try:
        stamp = source.stat().st_mtime_ns
    except OSError:
        stamp = None
    return str(source), stamp


def _queue_view(records: list[dict]) -> list[dict]:
    output: list[dict] = []
    for row in records:
        output.append(
            {
                "Status": _status_label(row.get("queue_status")),
                "Supplier": row.get("supplier_name", ""),
                "GPI Item": row.get("gpi_item_no", ""),
                "Effective": row.get("effective_date", ""),
                "Cost Change": _float(row.get("supplier_cost_delta_pct")),
                "Customers": int(_float(row.get("affected_customers"))),
                "Est. Erosion": _float(row.get("estimated_margin_erosion")),
                "Lowest GP": _float(row.get("min_projected_gp_pct")),
                "Top Exposure": row.get("top_customer_no", ""),
                "Decision": str(row.get("decision") or ""),
            }
        )
    return output


def _customer_view(records: list[dict]) -> list[dict]:
    output: list[dict] = []
    for row in records:
        protected = str(row.get("special_pricing_protected") or "").strip().casefold()
        output.append(
            {
                "Customer": row.get("customer_no", ""),
                "Customer Name": row.get("customer_name", ""),
                "Rep": row.get("sales_rep", ""),
                "Sell": _float(row.get("recent_sell_median")),
                "Current Cost": _float(row.get("recent_cost_median")),
                "Projected Cost": _float(row.get("projected_cost")),
                "GP Now": _float(row.get("current_gp_pct")),
                "GP After": _float(row.get("projected_gp_pct")),
                "GP Drop": _float(row.get("gp_drop_points")),
                "12M Qty": _float(row.get("trailing_quantity")),
                "Erosion": _float(row.get("estimated_margin_erosion")),
                "Protected": protected in {"true", "1", "yes"},
            }
        )
    return output


def main() -> None:
    st.set_page_config(
        page_title="GPI Supplier Cost Cockpit",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.title("GPI Commercial Guardrail")
    st.caption("Supplier Cost Review Cockpit | human approval required | no Business Central writes")

    with st.sidebar:
        st.header("Data sources")
        queue_path = st.text_input("Approval queue CSV", value=DEFAULT_QUEUE)
        detail_path = st.text_input("Margin impact detail CSV", value=DEFAULT_DETAIL)
        decision_path = st.text_input("Decision log CSV", value=DEFAULT_DECISIONS)
        st.caption("These are local POC files. The cockpit does not query or update Business Central.")
        if st.button("Reload local files"):
            st.session_state["_supplier_cockpit_signature"] = None
            st.rerun()

    queue_records = load_csv_records(queue_path)
    if not queue_records:
        st.warning(
            "No approval queue rows were found. Run bc_supplier_approval_queue_cli first or select a queue CSV in the sidebar."
        )
        return

    detail_records = load_csv_records(detail_path)
    saved_decisions = load_csv_records(decision_path)
    signature = (
        _file_stamp(queue_path),
        _file_stamp(detail_path),
        _file_stamp(decision_path),
    )
    if st.session_state.get("_supplier_cockpit_signature") != signature:
        st.session_state["_supplier_cockpit_records"] = merge_saved_decisions(
            queue_records,
            saved_decisions,
        )
        st.session_state["_supplier_cockpit_signature"] = signature

    working_records = list(st.session_state.get("_supplier_cockpit_records", queue_records))
    summary = summarize_queue(working_records)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Approval items", int(summary["items"]))
    col2.metric("Protected items", int(summary["protected_items"]))
    col3.metric("Affected customers", int(summary["affected_customers"]))
    col4.metric("Protected customers", int(summary["protected_customers"]))
    col5.metric("Actionable erosion", _money(summary["estimated_margin_erosion"]))

    st.subheader("Approval queue")
    statuses = sorted(
        {
            str(row.get("queue_status") or "").strip().upper()
            for row in working_records
            if row.get("queue_status")
        }
    )
    f1, f2, f3 = st.columns([2, 2, 3])
    status_choice = f1.segmented_control(
        "Status",
        ["ALL", *statuses],
        default="ALL",
        format_func=_status_label,
    )
    supplier_filter = f2.text_input("Supplier contains")
    item_filter = f3.text_input("GPI item contains")

    wanted_statuses = [] if not status_choice or status_choice == "ALL" else [status_choice]
    filtered = filter_records(
        working_records,
        statuses=wanted_statuses,
        supplier_text=supplier_filter,
        item_text=item_filter,
    )

    if not filtered:
        st.info("No queue rows match the current filters.")
        return

    st.dataframe(
        _queue_view(filtered),
        width="stretch",
        hide_index=True,
        column_config={
            "Status": st.column_config.TextColumn("Status", width="medium"),
            "Supplier": st.column_config.TextColumn("Supplier", width="medium"),
            "GPI Item": st.column_config.TextColumn("GPI Item", width="medium"),
            "Effective": st.column_config.TextColumn("Effective", width="small"),
            "Cost Change": st.column_config.NumberColumn("Cost Change", format="%.1f%%"),
            "Customers": st.column_config.NumberColumn("Customers", format="%d"),
            "Est. Erosion": st.column_config.NumberColumn("Est. Erosion", format="$%.2f"),
            "Lowest GP": st.column_config.NumberColumn("Lowest GP", format="%.1f%%"),
            "Top Exposure": st.column_config.TextColumn("Top Exposure", width="small"),
            "Decision": st.column_config.TextColumn("Decision", width="small"),
        },
    )

    item_index = st.selectbox(
        "Review item",
        options=list(range(len(filtered))),
        format_func=lambda index: (
            f"{filtered[index].get('gpi_item_no', '')}  |  "
            f"{filtered[index].get('supplier_name', '')}  |  "
            f"effective {filtered[index].get('effective_date', '')}"
        ),
    )
    selected = filtered[item_index]
    selected_item = str(selected.get("gpi_item_no") or "")
    selected_key = record_key(selected)
    selected_status = str(selected.get("queue_status") or "").strip().upper()

    st.divider()
    st.subheader(f"Item review: {selected_item}")
    st.caption(
        f"{selected.get('supplier_name', '')} | supplier item {selected.get('supplier_item_no', '') or 'n/a'} "
        f"| effective {selected.get('effective_date', '') or 'n/a'} | {selected.get('uom', '')}"
    )

    if selected_status == "PROTECTED_REVIEW":
        st.warning(
            "Protected pricing is active for at least one affected customer. This item cannot be approved in the generic cockpit."
        )
    else:
        st.info("This item passed the supplier-cost validation pipeline and is waiting for a human commercial decision.")

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Current supplier cost", f"{_money4(selected.get('supplier_current_cost'))}/{selected.get('uom', '')}")
    m2.metric("Proposed supplier cost", f"{_money4(selected.get('supplier_new_cost'))}/{selected.get('uom', '')}")
    m3.metric("Supplier increase", _pct(selected.get("supplier_cost_delta_pct")))
    m4.metric("Actionable erosion", _money(selected.get("estimated_margin_erosion")))
    m5.metric("Lowest projected GP", _pct(selected.get("min_projected_gp_pct")))
    m6.metric("Affected customers", int(_float(selected.get("affected_customers"))))

    st.write(f"**Top exposure:** {selected.get('top_customer_no', '')} / {_money(selected.get('top_customer_erosion'))}")
    st.write(f"**Review action:** {selected.get('action', '')}")
    if str(selected.get("pricing_approvers") or "").strip():
        st.write(f"**Pricing approver:** {selected.get('pricing_approvers')}")

    customer_rows = detail_rows_for_item(detail_records, selected_item)
    detail_col, decision_col = st.columns([3, 1])

    with detail_col:
        st.markdown("#### Customer margin impact")
        if customer_rows:
            st.dataframe(
                _customer_view(customer_rows),
                width="stretch",
                hide_index=True,
                column_config={
                    "Customer": st.column_config.TextColumn("Customer", width="small"),
                    "Customer Name": st.column_config.TextColumn("Customer Name", width="medium"),
                    "Rep": st.column_config.TextColumn("Rep", width="small"),
                    "Sell": st.column_config.NumberColumn("Sell", format="$%.2f"),
                    "Current Cost": st.column_config.NumberColumn("Current Cost", format="$%.2f"),
                    "Projected Cost": st.column_config.NumberColumn("Projected Cost", format="$%.2f"),
                    "GP Now": st.column_config.NumberColumn("GP Now", format="%.1f%%"),
                    "GP After": st.column_config.NumberColumn("GP After", format="%.1f%%"),
                    "GP Drop": st.column_config.NumberColumn("GP Drop", format="%.1f pts"),
                    "12M Qty": st.column_config.NumberColumn("12M Qty", format="%.2f"),
                    "Erosion": st.column_config.NumberColumn("Erosion", format="$%.2f"),
                    "Protected": st.column_config.CheckboxColumn("Protected"),
                },
            )
        else:
            st.info(
                "No customer-detail rows were found for this item. Generate the margin-impact CSV to add customer drill-down."
            )

    with decision_col:
        st.markdown("#### Human decision")
        current_decision = str(selected.get("decision") or "").strip().upper()
        options = list(DECISION_OPTIONS)
        if selected_status == "PROTECTED_REVIEW":
            options = [option for option in options if option != "APPROVE"]
        if current_decision not in options:
            current_decision = ""
        key_text = "|".join(selected_key)
        decision = st.selectbox(
            "Decision",
            options=options,
            index=options.index(current_decision),
            format_func=lambda value: "Choose..." if not value else value.title(),
            key=f"decision:{key_text}",
        )
        decision_by = st.text_input(
            "Reviewed by",
            value=str(selected.get("decision_by") or ""),
            key=f"decision_by:{key_text}",
        )
        decision_notes = st.text_area(
            "Notes",
            value=str(selected.get("decision_notes") or ""),
            height=120,
            key=f"decision_notes:{key_text}",
        )

        if st.button("Save decision", type="primary", width="stretch"):
            try:
                candidate = update_decision(
                    working_records,
                    selected_key,
                    decision=decision,
                    decision_by=decision_by,
                    decision_notes=decision_notes,
                )
                errors = validate_decisions(candidate)
                if errors:
                    raise ValueError(" | ".join(errors))
                write_decision_csv(candidate, decision_path)
            except (OSError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.session_state["_supplier_cockpit_records"] = candidate
                working_records = candidate
                st.success("Decision saved locally.")

        st.download_button(
            "Download decision log",
            data=records_to_csv(working_records),
            file_name=Path(decision_path).name,
            mime="text/csv",
            width="stretch",
        )
        st.caption("Saving here updates only the local decision log CSV.")

    st.divider()
    with st.expander("Technical/source details"):
        st.write(f"**Queue status:** {_status_label(selected_status)}")
        st.write(f"**Source file:** {selected.get('source_file', '')} row {selected.get('source_row', '')}")
        st.write(f"**Trailing quantity:** {_float(selected.get('trailing_quantity')):,.2f} {selected.get('uom', '')}")
        st.write(f"**Trailing sales:** {_money(selected.get('trailing_sales'))}")
        st.write(f"**Worst GP drop:** {_float(selected.get('max_gp_drop_points')):.1f} point(s)")

    st.caption(
        "Safety: decisions are local review records only. The cockpit does not update Business Central item costs, purchase prices, sales prices, or pricing guardrails."
    )


if __name__ == "__main__":
    main()
