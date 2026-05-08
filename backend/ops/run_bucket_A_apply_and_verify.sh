#!/usr/bin/env bash
# ops/run_bucket_A_apply_and_verify.sh
# ====================================
# One-shot guarded operator command for the Bucket A live apply.
#
# Strict scope:
#   - Re-runs the preflight (read-only).
#   - Refuses to apply if preflight is not PASS (exit 0).
#   - Idempotent: if every candidate is already in the expected
#     post-apply state, the apply step is SKIPPED (no-op) and the
#     wrapper continues to verify + proof pack. The wrapper does NOT
#     require a fresh apply when the approved patch is already present.
#   - Otherwise runs the gated apply with `--apply --confirm CUTOVER`.
#   - Verifies the post-apply state of the two approved doc IDs.
#   - Re-runs the read-only proof pack so the new match rate is visible.
#
# This script does NOT trigger Square9 cutover, archive Square9 stage
# data, populate any CFO summary, touch DocuSign / HTTPS / parked AP
# contamination work, or change routing / classifier logic.
#
# Usage on VM (after `git pull`):
#   docker compose exec backend bash ops/run_bucket_A_apply_and_verify.sh
#
# Optional override for tests:
#   BUCKET_A_APP_ROOT=/tmp/fake_app  bash ops/run_bucket_A_apply_and_verify.sh
#
# Approved doc IDs (from operator):
#   - 9391f78f-33c2-4186-9199-7df2da1124bb
#   - 5fe1d5c2-275c-4bbd-a693-6073a0fe9567

set -uo pipefail
cd "${BUCKET_A_APP_ROOT:-/app}"

APPROVED_IDS=(
    "9391f78f-33c2-4186-9199-7df2da1124bb"
    "5fe1d5c2-275c-4bbd-a693-6073a0fe9567"
)

PREFLIGHT_TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
PREFLIGHT_PROOF_DIR="${BUCKET_A_PREFLIGHT_DIR:-/tmp/bucket_A_preflight_${PREFLIGHT_TS}}"
PREFLIGHT_JSON="${PREFLIGHT_PROOF_DIR}/BUCKET_A_APPLY_PREFLIGHT.json"
mkdir -p "${PREFLIGHT_PROOF_DIR}"

echo
echo "##############################################################"
echo "# Step 1: Read-only preflight"
echo "##############################################################"
set +e
python scripts/bucket_A_apply_preflight.py --proof-dir "${PREFLIGHT_PROOF_DIR}"
PREFLIGHT_RC=$?
set -e
echo "[guard] preflight exit code = ${PREFLIGHT_RC}"

echo
echo "##############################################################"
echo "# Step 2: Wrapper decision (apply / skip_apply / abort)"
echo "##############################################################"
set +e
python scripts/bucket_A_wrapper_decision.py "${PREFLIGHT_JSON}"
DECISION_RC=$?
DECISION_LINE="$(python scripts/bucket_A_wrapper_decision.py \
    "${PREFLIGHT_JSON}" 2>/dev/null | grep '^DECISION=' | head -1)"
DECISION="${DECISION_LINE#DECISION=}"
set -e
echo "[guard] decision = ${DECISION:-<unknown>} (rc=${DECISION_RC})"

if [ "${DECISION}" != "apply" ] && [ "${DECISION}" != "skip_apply" ]; then
    echo "[guard] REFUSING APPLY: decision='${DECISION}'."
    echo "[guard] Inspect the preflight output and the JSON at:"
    echo "[guard]   ${PREFLIGHT_JSON}"
    exit "${DECISION_RC}"
fi

echo
echo "##############################################################"
if [ "${DECISION}" = "apply" ]; then
    echo "# Step 3: Gated apply (live writes; --apply --confirm CUTOVER)"
    echo "##############################################################"
    set +e
    python scripts/bucket_A_one_shot_data_patch_apply.py \
        --apply --confirm CUTOVER
    APPLY_RC=$?
    set -e
    echo "[guard] apply exit code = ${APPLY_RC}"
else
    echo "# Step 3: Apply SKIPPED — every candidate is already in the"
    echo "#         expected post-apply state (idempotent success)."
    echo "##############################################################"
    APPLY_RC=0
    echo "[guard] apply skipped; APPLY_RC=${APPLY_RC}"
fi

echo
echo "##############################################################"
echo "# Step 4: Verify post-apply state of approved doc IDs"
echo "##############################################################"
set +e
python scripts/verify_bucket_A_apply.py --ids "${APPROVED_IDS[@]}"
VERIFY_RC=$?
set -e
echo "[guard] verify exit code = ${VERIFY_RC}"

echo
echo "##############################################################"
echo "# Step 5: Re-run read-only proof pack (fresh match rate)"
echo "##############################################################"
set +e
bash ops/prod_verify_square9_cutover_readiness.sh
PROOF_RC=$?
set -e
echo "[guard] proof pack exit code = ${PROOF_RC}"

echo
echo "##############################################################"
echo "# SUMMARY"
echo "##############################################################"
echo "  preflight_exit_code     : ${PREFLIGHT_RC}  (0=PASS)"
echo "  decision                : ${DECISION}"
echo "  apply_exit_code         : ${APPLY_RC}      (0=skipped /"
echo "                                              4=updates applied /"
echo "                                              5=already idempotent)"
echo "  verify_exit_code        : ${VERIFY_RC}     (0=all approved IDs found)"
echo "  proof_pack_exit_code    : ${PROOF_RC}      (0=GO / 1=NO-GO)"
echo "  preflight_json          : ${PREFLIGHT_JSON}"
echo "  approved_ids:"
for i in "${APPROVED_IDS[@]}"; do
    echo "    - ${i}"
done
echo
echo "  Read the proof-pack summary above for the new match_rate_pct, "
echo "  the projected match rate, and any remaining blockers / cohort counts."
echo
echo "  READ-ONLY beyond the gated apply step. No Square9 cutover, "
echo "  no archive, no CFO summary, no DocuSign/HTTPS/contamination work."

exit "${PROOF_RC}"
