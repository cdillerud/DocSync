#!/usr/bin/env bash
# ops/run_bucket_A_apply_and_verify.sh
# ====================================
# One-shot guarded operator command for the Bucket A live apply.
#
# Strict scope:
#   - Re-runs the preflight (read-only).
#   - Refuses to apply if preflight is not PASS (exit 0).
#   - Runs the gated apply with `--apply --confirm CUTOVER`.
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
# Approved doc IDs (from operator):
#   - 9391f78f-33c2-4186-9199-7df2da1124bb
#   - 5fe1d5c2-275c-4bbd-a693-6073a0fe9567

set -uo pipefail
cd /app

APPROVED_IDS=(
    "9391f78f-33c2-4186-9199-7df2da1124bb"
    "5fe1d5c2-275c-4bbd-a693-6073a0fe9567"
)

echo
echo "##############################################################"
echo "# Step 1: Read-only preflight"
echo "##############################################################"
set +e
python scripts/bucket_A_apply_preflight.py
PREFLIGHT_RC=$?
set -e
echo "[guard] preflight exit code = ${PREFLIGHT_RC}"
if [ "${PREFLIGHT_RC}" -ne 0 ]; then
    echo "[guard] REFUSING APPLY: preflight did not return 0 (PASS)."
    echo "[guard] Inspect the preflight output above and rerun once it is PASS."
    exit "${PREFLIGHT_RC}"
fi

echo
echo "##############################################################"
echo "# Step 2: Gated apply (live writes; --apply --confirm CUTOVER)"
echo "##############################################################"
set +e
python scripts/bucket_A_one_shot_data_patch_apply.py --apply --confirm CUTOVER
APPLY_RC=$?
set -e
echo "[guard] apply exit code = ${APPLY_RC}"

echo
echo "##############################################################"
echo "# Step 3: Verify post-apply state of approved doc IDs"
echo "##############################################################"
set +e
python scripts/verify_bucket_A_apply.py --ids "${APPROVED_IDS[@]}"
VERIFY_RC=$?
set -e
echo "[guard] verify exit code = ${VERIFY_RC}"

echo
echo "##############################################################"
echo "# Step 4: Re-run read-only proof pack (fresh match rate)"
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
echo "  apply_exit_code         : ${APPLY_RC}      (4=updates applied / "
echo "                                              5=already idempotent)"
echo "  verify_exit_code        : ${VERIFY_RC}     (0=all approved IDs found)"
echo "  proof_pack_exit_code    : ${PROOF_RC}      (0=GO / 1=NO-GO)"
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
