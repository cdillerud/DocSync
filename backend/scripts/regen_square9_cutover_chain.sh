#!/usr/bin/env bash
# regen_square9_cutover_chain.sh
# ==============================
# One-shot regenerator for the full Square9 cutover analysis chain. Run
# this ONCE on the VM after pulling. It rebuilds every artifact under
# prod_reports/ in dependency order:
#
#   1. square9_hub_ap_parity_report.py
#   2. square9_only_triage_resolver.py        (consumes square9_only_triage.csv)
#   3. bucket_A_root_cause_report.py
#   4. bucket_C_intake_gap_report.py
#   5. investigate_blank_square9_metadata.py  (cleans Bucket C contamination)
#   6. investigate_low_confidence_bucket_A.py (cleans Bucket A contamination)
#   7. bucket_A_misrouting_remediation_plan.py
#   8. bucket_C_intake_remediation_plan.py
#   9. bucket_A_one_shot_data_patch_dryrun.py        (NEW: read-only)
#  10. bucket_A_routing_rule_addition_dryrun.py      (NEW: read-only)
#  11. bucket_C_handoff_doc.py                       (NEW: read-only)
#  12. ingest_bucket_A_corrections.py                (NEW: read-only preview)
#      Feeds verified, high-confidence Bucket A misclassifications into
#      the existing classification learning loop (classification_
#      corrections) - the same collection the live classification
#      pipeline already reads on every document via feedback_loop_
#      service.py::build_feedback_context_for_prompt. Runs in dry-run
#      preview mode here (matching every other step in this chain).
#      To actually teach the classifier what this run found:
#        docker compose exec backend python3 \
#          scripts/ingest_bucket_A_corrections.py --confirm \
#          --run-label "<proof_dir name>"
#
# Nothing in this chain mutates Mongo, the classifier, or routing rules.
# The final four steps are read-only previews of what an apply step
# WOULD do.
#
# Exit status:
#   0  every step completed; review prod_reports/
#   non-zero  the failing step's exit code; pipeline halts immediately
#
# Usage on VM (after `git pull` and `docker compose up -d backend`):
#   docker compose exec backend bash scripts/regen_square9_cutover_chain.sh

set -euo pipefail

cd /app

step() {
    local label="$1"
    shift
    echo
    echo "=================================================================="
    echo "[regen] $label"
    echo "         $*"
    echo "=================================================================="
    # Each script may legitimately exit with non-zero rcs to signal
    # workflow state (e.g. dry-run scripts use 0/1/2). We treat any
    # exit code <= 2 as "completed" and only halt on >= 3.
    set +e
    "$@"
    local rc=$?
    set -e
    if [ "$rc" -ge 3 ]; then
        echo "[regen] FAIL: '$label' exited with rc=$rc — halting pipeline."
        exit "$rc"
    fi
    echo "[regen] OK : '$label' rc=$rc"
}

mkdir -p prod_reports

step "1/12 square9_hub_ap_parity_report" \
    python scripts/square9_hub_ap_parity_report.py

step "2/12 square9_only_triage_resolver" \
    python scripts/square9_only_triage_resolver.py \
        --triage-csv prod_reports/square9_only_triage.csv

step "3/12 bucket_A_root_cause_report" \
    python scripts/bucket_A_root_cause_report.py

step "4/12 bucket_C_intake_gap_report" \
    python scripts/bucket_C_intake_gap_report.py

step "5/12 investigate_blank_square9_metadata" \
    python scripts/investigate_blank_square9_metadata.py

step "6/12 investigate_low_confidence_bucket_A" \
    python scripts/investigate_low_confidence_bucket_A.py

step "7/12 bucket_A_misrouting_remediation_plan" \
    python scripts/bucket_A_misrouting_remediation_plan.py

step "8/12 bucket_C_intake_remediation_plan" \
    python scripts/bucket_C_intake_remediation_plan.py

step "9/12 bucket_A_one_shot_data_patch_dryrun (READ-ONLY)" \
    python scripts/bucket_A_one_shot_data_patch_dryrun.py

step "10/12 bucket_A_routing_rule_addition_dryrun (READ-ONLY)" \
    python scripts/bucket_A_routing_rule_addition_dryrun.py

step "11/12 bucket_C_handoff_doc (READ-ONLY)" \
    python scripts/bucket_C_handoff_doc.py

step "12/12 ingest_bucket_A_corrections (READ-ONLY preview)" \
    python scripts/ingest_bucket_A_corrections.py --run-label "regen_$(date -u +%Y%m%dT%H%M%SZ)"

echo
echo "=================================================================="
echo "[regen] DONE. Artifacts in prod_reports/:"
echo "=================================================================="
ls -1 prod_reports/ | grep -E "^(square9|bucket_|low_confidence|blank_)" | sort
echo
echo "Cutover-critical artifacts:"
for f in \
    prod_reports/square9_hub_ap_parity.csv \
    prod_reports/bucket_A_remediation_plan.json \
    prod_reports/bucket_C_remediation_plan.json \
    prod_reports/bucket_A_one_shot_data_patch_dryrun.csv \
    prod_reports/bucket_A_routing_rule_addition_dryrun.csv \
    prod_reports/bucket_C_handoff.md \
    prod_reports/bucket_C_handoff.csv \
    prod_reports/bucket_A_corrections_preview.json ; do
    if [ -f "$f" ]; then
        printf "  OK    %s  (%s bytes)\n" "$f" "$(stat -c%s "$f")"
    else
        printf "  MISS  %s\n" "$f"
    fi
done
