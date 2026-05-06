#!/usr/bin/env bash
# ops/prod_verify_square9_cutover_readiness.sh
# ============================================
# READ-ONLY proof pack for the Square9 cutover.
#
# Runs every cutover-readiness probe in dependency order, captures stdout
# / stderr / rc per step, dumps every produced artifact under a single
# timestamped directory, then renders a final GO / NO-GO summary based
# on per-step exit codes plus the parity report's match_rate_pct.
#
# This script is *strictly* read-only:
#   - no Mongo writes
#   - no Exchange / mailbox source changes
#   - no Square9 cutover toggle
#   - no archive-stage-data
#   - no transport-rule changes
#   - no document reclassification
#
# Stages (dependency order):
#   1.  ap_cutover_readiness_report
#   2.  billing_intake_routing_probe
#   3.  square9_hub_ap_parity_report
#   4.  square9_only_triage_resolver
#   5.  bucket_A_root_cause_report
#   6.  bucket_C_intake_gap_report
#   7.  bucket_A_misrouting_remediation_plan
#   8.  bucket_C_intake_remediation_plan
#   9.  email_poll_watermark_probe        (mail_poll_runs health summary)
#
# Exit codes from the *individual* stages are NOT a failure per se: the
# repo's conventions use 0/1/2 as workflow signal codes. Anything >= 3
# is treated as a hard failure and bubbles up via cutover_proof_summary.
#
# Final exit code is the summary's exit code:
#   0  GO  — all stages completed and match_rate_pct >= --min-match-rate
#   1  NO-GO — at least one blocker recorded
#
# Usage:
#   docker compose exec backend bash ops/prod_verify_square9_cutover_readiness.sh
#
# Optional:
#   MIN_MATCH_RATE=85.0  ops/prod_verify_square9_cutover_readiness.sh

set -uo pipefail

cd /app

MIN_MATCH_RATE="${MIN_MATCH_RATE:-85.0}"
# Default to 168 hours (1 week). Matches the cutover deadline window,
# guarantees the 24h-default-empty stages (triage / Bucket A / Bucket C)
# actually have rows to process, and is overridable via env:
#   docker compose exec -e PROOF_SINCE_HOURS=720 backend bash ops/...
PROOF_SINCE_HOURS="${PROOF_SINCE_HOURS:-168}"
TIMESTAMP="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
PROOF_DIR="prod_reports/cutover_proof_${TIMESTAMP}"
LOG_DIR="${PROOF_DIR}/logs"
ARTIFACT_DIR="${PROOF_DIR}/artifacts"
MANIFEST="${PROOF_DIR}/manifest.json"

mkdir -p "${LOG_DIR}" "${ARTIFACT_DIR}"

STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "[proof] dir=${PROOF_DIR}  started=${STARTED_AT}  min_match_rate=${MIN_MATCH_RATE}  since_hours=${PROOF_SINCE_HOURS}"

# Manifest is built incrementally as a JSON array of step objects.
echo "{" > "${MANIFEST}"
{
    echo "  \"proof_dir\": \"${PROOF_DIR}\","
    echo "  \"started_at_utc\": \"${STARTED_AT}\","
    echo "  \"min_match_rate_pct\": ${MIN_MATCH_RATE},"
    echo "  \"steps\": ["
} >> "${MANIFEST}"

FIRST_STEP=1

run_step() {
    local id="$1"
    local label="$2"
    shift 2
    local log_path="${LOG_DIR}/${id}.log"
    local started rc finished duration

    echo
    echo "------------------------------------------------------------------"
    echo "[proof] [${id}] ${label}"
    echo "         cmd: $*"
    echo "         log: ${log_path}"
    echo "------------------------------------------------------------------"

    started=$(date +%s)
    # Capture both stdout + stderr; preserve rc; do not abort the script.
    set +e
    "$@" >"${log_path}" 2>&1
    rc=$?
    set -e
    finished=$(date +%s)
    duration=$(( finished - started ))

    # Tracebacks override workflow-signal exit codes. Several scripts in
    # this repo use rc=1/2 as legitimate workflow signals (e.g. parity
    # blockers), but Python's default exception exit code is also 1, so
    # a crashed downstream script looks identical to a clean signal.
    # If the log contains a Python traceback, force rc>=3 so the
    # summarizer classifies the step as a hard failure.
    local crashed=0
    if grep -qE '^Traceback \(most recent call last\):' "${log_path}"; then
        crashed=1
        if [ "$rc" -lt 3 ]; then
            rc=3
        fi
    fi

    if [ "$crashed" -eq 1 ]; then
        echo "[proof] [${id}] FAIL rc=${rc} (Python traceback detected)  (${duration}s) — see ${log_path}"
    elif [ "$rc" -eq 0 ]; then
        echo "[proof] [${id}] OK rc=0  (${duration}s)"
    elif [ "$rc" -le 2 ]; then
        echo "[proof] [${id}] OK_SIGNAL rc=${rc}  (${duration}s)"
    else
        echo "[proof] [${id}] FAIL rc=${rc}  (${duration}s) — see ${log_path}"
    fi

    if [ "$FIRST_STEP" -eq 1 ]; then
        FIRST_STEP=0
    else
        echo "    ," >> "${MANIFEST}"
    fi
    {
        printf '    {'
        printf '"id": "%s", ' "${id}"
        printf '"label": "%s", ' "${label}"
        printf '"cmd": "%s", ' "$*"
        printf '"rc": %d, ' "${rc}"
        printf '"duration_sec": %d, ' "${duration}"
        printf '"log_path": "%s"' "${log_path}"
        printf '}'
    } >> "${MANIFEST}"
    echo "" >> "${MANIFEST}"
}

# --- 1. AP cutover readiness report ----------------------------------------
run_step ap_cutover_readiness_report \
    "AP cutover readiness report" \
    python scripts/ap_cutover_readiness_report.py --json \
        --since-hours "${PROOF_SINCE_HOURS}"

# --- 2. Billing intake routing probe ---------------------------------------
run_step billing_intake_routing_probe \
    "Billing intake routing probe" \
    python scripts/billing_intake_routing_probe.py --json \
        --since-hours "${PROOF_SINCE_HOURS}"

# --- 3. Square9 Hub-AP parity report ---------------------------------------
run_step square9_hub_ap_parity_report \
    "Square9 Hub-AP parity report" \
    python scripts/square9_hub_ap_parity_report.py --json \
        --since-hours "${PROOF_SINCE_HOURS}"

# --- 4. Square9-only triage resolver ---------------------------------------
run_step square9_only_triage_resolver \
    "Square9-only triage resolver" \
    python scripts/square9_only_triage_resolver.py \
        --triage-csv prod_reports/square9_only_triage.csv \
        --since-hours "${PROOF_SINCE_HOURS}"

# --- 5. Bucket A root-cause report -----------------------------------------
run_step bucket_A_root_cause_report \
    "Bucket A root-cause report" \
    python scripts/bucket_A_root_cause_report.py

# --- 6. Bucket C intake-gap report -----------------------------------------
run_step bucket_C_intake_gap_report \
    "Bucket C intake-gap report" \
    python scripts/bucket_C_intake_gap_report.py

# --- 7. Bucket A remediation plan ------------------------------------------
run_step bucket_A_misrouting_remediation_plan \
    "Bucket A misrouting remediation plan" \
    python scripts/bucket_A_misrouting_remediation_plan.py

# --- 8. Bucket C remediation plan ------------------------------------------
run_step bucket_C_intake_remediation_plan \
    "Bucket C intake remediation plan" \
    python scripts/bucket_C_intake_remediation_plan.py

# --- 9. mail_poll_runs health summary --------------------------------------
run_step email_poll_watermark_probe \
    "mail_poll_runs health summary" \
    python scripts/email_poll_watermark_probe.py

# --- Manifest close ---------------------------------------------------------
FINISHED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
{
    echo "  ],"
    echo "  \"finished_at_utc\": \"${FINISHED_AT}\""
    echo "}"
} >> "${MANIFEST}"

# --- Snapshot the parity JSON into the proof dir for the summarizer --------
if [ -f prod_reports/square9_hub_ap_parity.json ]; then
    cp -f prod_reports/square9_hub_ap_parity.json "${PROOF_DIR}/square9_hub_ap_parity.json"
fi

# --- Final summary ---------------------------------------------------------
python ops/cutover_proof_summary.py \
    --proof-dir "${PROOF_DIR}" \
    --min-match-rate "${MIN_MATCH_RATE}"
SUMMARY_RC=$?

echo
echo "[proof] Manifest:    ${MANIFEST}"
echo "[proof] Logs:        ${LOG_DIR}/"
echo "[proof] Summary JSON ${PROOF_DIR}/summary.json"
echo "[proof] Summary MD:  ${PROOF_DIR}/summary.md"
echo "[proof] Final exit:  ${SUMMARY_RC}  (0=GO, 1=NO-GO)"

exit "${SUMMARY_RC}"
