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
    validate_detail_consistency,
    write_decision_csv,
)
from poc.commercial_guardrails.supplier_review_pipeline import (
    SUPPORTED_SUPPLIER_NOTICE_EXTENSIONS,
    create_manual_supplier_review_run,
)


DEFAULT_QUEUE = "poc/commercial_guardrails/live_supplier_approval_queue.csv"
DEFAULT_DETAIL = "poc/commercial_guardrails/live_supplier_margin_impact.csv"
DEFAULT_DECISIONS = "poc/commercial_guardrails/live_supplier_approval_decisions.csv"
QUEUE_PATH_KEY = "_supplier_cockpit_queue_path"
DETAIL_PATH_KEY = "_supplier_cockpit_detail_path"
DECISION_PATH_KEY = "_supplier_cockpit_decision_path"


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


def _initialize_path_state() -> None:
    st.session_state.setdefault(QUEUE_PATH_KEY, DEFAULT_QUEUE)
    st.session_state.setdefault(DETAIL_PATH_KEY, DEFAULT_DETAIL)
    st.session_state.setdefault(DECISION_PATH_KEY, DEFAULT_DECISIONS)


def _clear_decision_widget_state() -> None:
    """Prevent decision form values from leaking from one review snapshot into another."""
    prefixes = ("decision:", "decision_by:", "decision_notes:")
    for key in list(st.session_state.keys()):
        if str(key).startswith(prefixes):
            del st.session_state[key]


def _activate_run(artifacts) -> None:
    st.session_state[QUEUE_PATH_KEY] = str(artifacts.queue_path)
    st.session_state[DETAIL_PATH_KEY] = str(artifacts.detail_path)
    st.session_state[DECISION_PATH_KEY] = str(artifacts.decision_path)
    st.session_state["_supplier_cockpit_signature"] = None
    st.session_state.pop("_supplier_cockpit_records", None)
    _clear_decision_widget_state()
    summary = artifacts.review_run.summary
    st.session_state["_supplier_cockpit_flash"] = (
        f"Analyzed {artifacts.source_path.name}. "
        f"{summary['items']} approval item(s), {summary['review_rows']} review row(s), "
        f"{summary['reject_rows']} rejected row(s), {_money(summary['estimated_margin_erosion'])} actionable erosion."
    )


def main() -> None:
    st.set_page_config(
        page_title="GPI Supplier Cost Cockpit",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _initialize_path_state()

    st.title("GPI Commercial Guardrail")
    st.caption("Supplier Cost Review Cockpit | human approval required | no Business Central writes")

    flash = st.session_state.pop("_supplier_cockpit_flash", "")
    if flash:
        st.success(flash)

    # Manual intake is intentionally the first real-source workflow. It creates a
    # self-contained local run folder and performs only read operations against BC.
    with st.expander("New supplier notice", expanded=False):
        st.write("Upload a supplier CSV or Excel notice and run the validated read-only analysis pipeline.")
        uploaded_notice = st.file_uploader(
            "Supplier notice",
            type=[suffix.lstrip(".") for suffix in SUPPORTED_SUPPLIER_NOTICE_EXTENSIONS],
            accept_multiple_files=False,
            key="_supplier_cockpit_upload",
        )
        u1, u2, u3 = st.columns([2, 2, 2])
        start_date = u1.text_input("History start", value="2024-01-01")
        default_supplier = u2.text_input("Default supplier", value="")
        sheet_name = u3.text_input("Excel sheet (optional)", value="")
        st.caption(
            "The uploaded source is copied into an auditable local run folder with its queue, margin detail, manifest, and decision log. "
            "This does not monitor email and does not write to Business Central."
        )

        if st.button(
            "Analyze and open review",
            type="primary",
            disabled=uploaded_notice is None,
            key="_supplier_cockpit_analyze_upload",
        ):
            try:
                with st.spinner("Reading Business Central history and building the review queue..."):
                    artifacts = create_manual_supplier_review_run(
                        uploaded_notice.name,
                        uploaded_notice.getvalue(),
                        start_date=start_date.strip() or "2024-01-01",
                        default_supplier=default_supplier.strip(),
                        sheet_name=sheet_name.strip(),
                    )
            except (OSError, RuntimeError, ValueError) as exc:
                st.error(str(exc))
            else:
                _activate_run(artifacts)
                st.rerun()

    with st.sidebar:
        st.header("Data sources")
        queue_path = st.text_input("Approval queue CSV", key=QUEUE_PATH_KEY)
        detail_path = st.text_input("Margin impact detail CSV", key=DETAIL_PATH_KEY)
        decision_path = st.text_input("Decision log CSV", key=DECISION_PATH_KEY)
        st.caption("These are local POC files. The cockpit does not update Business Central.")
        if st.button("Reload local files"):
            st.session_state["_supplier_cockpit_signature"] = None
            st.rerun()

    queue_parent = Path(queue_path).parent
    if Path(queue_path).name == "approval_queue.csv" and queue_parent.name:
        st.caption(f"Active review run: {queue_parent.name}")

    queue_records = load_csv_records(queue_path)
    if not queue_records:
        st.warning(
            "No approval queue rows were found. Upload a new supplier notice above, or select an existing queue CSV in the sidebar."
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
        _clear_decision_widget_state()
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

    statuses = sorted(
        {
            str(row.get("queue_status") or "").strip().upper()
            for row in working_records
            if row.get("queue_status")
        }
    )

    with st.expander(f"Browse approval queue ({len(working_records)} item(s))", expanded=False):
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

        if filtered:
            st.dataframe(
                _queue_view(filtered),
                use_container_width=True,
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
        else:
            st.info("No queue rows match the current filters.")

    item_index = st.selectbox(
        "Review item",
        options=list(range(len(working_records))),
        format_func=lambda index: (
            f"{working_records[index].get('gpi_item_no', '')}  |  "
            f"{working_records[index].get('supplier_name', '')}  |  "
            f"effective {working_records[index].get('effective_date', '')}"
        ),
    )
    selected = working_records[item_index]
    selected_item = str(selected.get("gpi_item_no") or "")
    selected_key = record_key(selected)
    selected_status = str(selected.get("queue_status") or "").strip().upper()
    customer_rows = detail_rows_for_item(detail_records, selected_item)
    detail_errors = validate_detail_consistency(selected, customer_rows)
    total_erosion = _float(selected.get("estimated_margin_erosion"))
    top_erosion = _float(selected.get("top_customer_erosion"))
    top_exposure_share = (top_erosion / total_erosion * 100.0) if total_erosion > 0 else 0.0

    st.subheader(f"Item review: {selected_item}")
    st.caption(
        f"{selected.get('supplier_name', '')} | supplier item {selected.get('supplier_item_no', '') or 'n/a'} "
        f"| effective {selected.get('effective_date', '') or 'n/a'} | {selected.get('uom', '')}"
    )

    if detail_errors:
        st.error(
            "Customer detail is out of sync with the approval queue. A decision is disabled until the "
            "queue and detail files are regenerated from the same analysis snapshot.\n\n"
            + "\n".join(f"- {error}" for error in detail_errors)
        )

    review_col, decision_col = st.columns([3, 1])

    with review_col:
        if selected_status == "PROTECTED_REVIEW":
            st.warning(
                "Protected pricing is active for at least one affected customer. This item cannot be approved in the generic cockpit."
            )
        else:
            st.info("This item passed the supplier-cost validation pipeline and is waiting for a human commercial decision.")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(
            "Supplier cost",
            f"{_money4(selected.get('supplier_new_cost'))}/{selected.get('uom', '')}",
            delta=(
                f"+{_money4(selected.get('supplier_cost_delta'))} / "
                f"{_pct(selected.get('supplier_cost_delta_pct'))}"
            ),
            delta_color="inverse",
        )
        m2.metric("Actionable erosion", _money(selected.get("estimated_margin_erosion")))
        m3.metric("Lowest projected GP", _pct(selected.get("min_projected_gp_pct")))
        m4.metric("Affected customers", int(_float(selected.get("affected_customers"))))

        st.write(
            f"**Current supplier cost:** {_money4(selected.get('supplier_current_cost'))}/"
            f"{selected.get('uom', '')}"
        )
        st.write(
            f"**Top exposure:** {selected.get('top_customer_no', '')} / "
            f"{_money(selected.get('top_customer_erosion'))} "
            f"({top_exposure_share:.1f}% of item exposure)"
        )
        st.write(f"**Review action:** {selected.get('action', '')}")
        if str(selected.get("pricing_approvers") or "").strip():
            st.write(f"**Pricing approver:** {selected.get('pricing_approvers')}")

        st.markdown("#### Customer margin impact")
        if detail_errors:
            st.warning(
                "Customer detail is suppressed because it was generated from a different analysis snapshot. "
                "Regenerate the approval queue to refresh the matching margin-detail sidecar."
            )
        elif customer_rows:
            st.dataframe(
                _customer_view(customer_rows),
                use_container_width=True,
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
        st.markdown("### Decision required")
        st.caption(
            f"{_status_label(selected_status)} | top exposure "
            f"{selected.get('top_customer_no', '')} {_money(selected.get('top_customer_erosion'))} "
            f"({top_exposure_share:.1f}%)"
        )
        if detail_errors:
            st.warning("Decision saving is disabled until the customer detail matches the approval queue.")
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
            height=140,
            key=f"decision_notes:{key_text}",
        )

        if st.button(
            "Save decision",
            type="primary",
            use_container_width=True,
            disabled=bool(detail_errors),
        ):
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
            use_container_width=True,
        )
        st.caption("Local review record only. No BC write.")

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
