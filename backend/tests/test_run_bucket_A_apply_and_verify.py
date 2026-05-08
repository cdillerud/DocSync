"""
Tests for the Bucket A wrapper:
  - scripts/bucket_A_wrapper_decision.py (pure Python decision)
  - ops/run_bucket_A_apply_and_verify.sh (bash, with stubs)

The bash test layout creates a fake $BUCKET_A_APP_ROOT containing stub
``scripts/`` and ``ops/`` directories. Stubs emit canned output, write
the preflight JSON the decision helper expects, and record their
invocation by appending to a CALL_LOG file. The real wrapper script is
copied in unchanged so we exercise its actual control flow.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts import bucket_A_wrapper_decision as wd


# ---------------------------------------------------------------------------
# Pure decide() unit tests
# ---------------------------------------------------------------------------

def _payload(rc=0, candidate=2, safe=0, already=0, unsafe=0):
    return {
        "exit_code": rc,
        "result": {
            "candidate_count": candidate,
            "safe_count": safe,
            "already_applied_count": already,
            "unsafe_count": unsafe,
        },
    }


def test_decide_apply_when_safe_candidates_present():
    d, r = wd.decide(_payload(rc=0, candidate=2, safe=2, already=0, unsafe=0))
    assert d == "apply"
    assert "2 safe" in r


def test_decide_apply_when_safe_and_already_applied_mixed():
    d, _ = wd.decide(_payload(rc=0, candidate=2, safe=1, already=1, unsafe=0))
    assert d == "apply"


def test_decide_skip_apply_when_all_already_applied():
    d, r = wd.decide(_payload(rc=0, candidate=2, safe=0, already=2, unsafe=0))
    assert d == "skip_apply"
    assert "all 2" in r


def test_decide_abort_when_unsafe_present():
    d, r = wd.decide(_payload(rc=1, candidate=2, safe=0, already=1, unsafe=1))
    assert d == "abort"
    assert "exit_code=1" in r or "unsafe" in r


def test_decide_abort_when_no_candidates():
    d, _ = wd.decide(_payload(rc=2, candidate=0))
    assert d == "abort"


def test_decide_abort_when_safe_zero_already_zero():
    # Pathological / impossible-but-defensive: nothing safe AND nothing
    # already applied. Wrapper must not run apply.
    d, _ = wd.decide(_payload(rc=0, candidate=2, safe=0, already=0, unsafe=0))
    assert d == "abort"


# ---------------------------------------------------------------------------
# Bash wrapper end-to-end tests (using stubs)
# ---------------------------------------------------------------------------

REAL_WRAPPER = Path(__file__).resolve().parents[1] / \
    "ops" / "run_bucket_A_apply_and_verify.sh"
REAL_DECISION_HELPER = Path(__file__).resolve().parents[1] / \
    "scripts" / "bucket_A_wrapper_decision.py"


def _make_executable(p: Path) -> None:
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _build_fake_app(tmp_path: Path,
                    preflight_payload: dict,
                    preflight_rc: int = 0,
                    proof_pack_rc: int = 0,
                    verify_rc: int = 0,
                    apply_rc: int = 4) -> Path:
    """Set up a self-contained app root the wrapper can run inside.

    The fake ``scripts/`` and ``ops/`` mimic the real layout: the
    preflight stub writes BUCKET_A_APPLY_PREFLIGHT.json with the
    supplied payload; the apply / verify / proof-pack stubs record
    their calls to ``CALL_LOG`` and return the supplied exit codes.
    The real decision helper and the real wrapper script are copied
    in (we want to exercise the actual control flow).
    """
    app_root = tmp_path / "fake_app"
    (app_root / "scripts").mkdir(parents=True)
    (app_root / "ops").mkdir(parents=True)

    call_log = app_root / "CALL_LOG"
    call_log.write_text("")

    def _stub_python(name: str, body: str) -> Path:
        path = app_root / "scripts" / name
        path.write_text("#!/usr/bin/env python3\n" + body)
        _make_executable(path)
        return path

    payload_json = json.dumps(preflight_payload)

    # Preflight stub: writes BUCKET_A_APPLY_PREFLIGHT.json into the
    # --proof-dir, prints the human banner + machine status line, and
    # exits with the supplied code.
    _stub_python(
        "bucket_A_apply_preflight.py",
        textwrap.dedent(f"""\
            import argparse, json, os, sys
            with open({str(call_log)!r}, "a") as f:
                f.write("preflight " + " ".join(sys.argv[1:]) + "\\n")
            p = argparse.ArgumentParser()
            p.add_argument("--proof-dir", required=True)
            p.add_argument("--plan-json", default=None)
            p.add_argument("--root-cause-csv", default=None)
            p.add_argument("--parity-json", default=None)
            args, _ = p.parse_known_args()
            os.makedirs(args.proof_dir, exist_ok=True)
            payload = {payload_json}
            with open(os.path.join(args.proof_dir,
                "BUCKET_A_APPLY_PREFLIGHT.json"), "w") as fh:
                json.dump(payload, fh)
            res = payload.get("result", {{}})
            print("[preflight-status] candidate_count={{}} safe_count={{}} "
                  "already_applied_count={{}} unsafe_count={{}}".format(
                  res.get("candidate_count", 0),
                  res.get("safe_count", 0),
                  res.get("already_applied_count", 0),
                  res.get("unsafe_count", 0)))
            sys.exit({preflight_rc})
        """),
    )

    # Apply stub: records and returns supplied rc.
    _stub_python(
        "bucket_A_one_shot_data_patch_apply.py",
        textwrap.dedent(f"""\
            import sys
            with open({str(call_log)!r}, "a") as f:
                f.write("apply " + " ".join(sys.argv[1:]) + "\\n")
            print("apply stub")
            sys.exit({apply_rc})
        """),
    )

    # Verify stub.
    _stub_python(
        "verify_bucket_A_apply.py",
        textwrap.dedent(f"""\
            import sys
            with open({str(call_log)!r}, "a") as f:
                f.write("verify " + " ".join(sys.argv[1:]) + "\\n")
            print("verify stub")
            sys.exit({verify_rc})
        """),
    )

    # Real decision helper (we want to test the actual logic).
    shutil.copy(REAL_DECISION_HELPER,
                app_root / "scripts" / "bucket_A_wrapper_decision.py")
    _make_executable(app_root / "scripts" / "bucket_A_wrapper_decision.py")

    # Proof-pack stub.
    proof = app_root / "ops" / "prod_verify_square9_cutover_readiness.sh"
    proof.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "proof-pack stub" >&2
        echo proof >> {call_log}
        exit {proof_pack_rc}
    """))
    _make_executable(proof)

    # Real wrapper.
    shutil.copy(REAL_WRAPPER,
                app_root / "ops" / "run_bucket_A_apply_and_verify.sh")
    _make_executable(app_root / "ops" / "run_bucket_A_apply_and_verify.sh")

    return app_root


def _run_wrapper(app_root: Path, preflight_dir: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["BUCKET_A_APP_ROOT"] = str(app_root)
    env["BUCKET_A_PREFLIGHT_DIR"] = str(preflight_dir)
    return subprocess.run(
        ["bash", "ops/run_bucket_A_apply_and_verify.sh"],
        cwd=app_root, env=env,
        capture_output=True, text=True, timeout=60,
    )


def _calls(app_root: Path) -> list:
    return (app_root / "CALL_LOG").read_text().splitlines()


def test_wrapper_skips_apply_when_all_already_applied(tmp_path: Path):
    payload = {
        "exit_code": 0,
        "result": {"candidate_count": 2, "safe_count": 0,
                   "already_applied_count": 2, "unsafe_count": 0},
    }
    app_root = _build_fake_app(tmp_path, preflight_payload=payload,
                               preflight_rc=0, proof_pack_rc=0)
    preflight_dir = tmp_path / "pf"
    res = _run_wrapper(app_root, preflight_dir)
    assert res.returncode == 0, res.stdout + res.stderr
    calls = _calls(app_root)
    # Apply must NOT have been invoked.
    assert not any(c.startswith("apply ") for c in calls), calls
    # Verify and proof pack still ran.
    assert any(c.startswith("verify ") for c in calls), calls
    assert any(c == "proof" for c in calls), calls
    assert "decision = skip_apply" in res.stdout
    assert "Apply SKIPPED" in res.stdout


def test_wrapper_runs_apply_when_safe_candidates_present(tmp_path: Path):
    payload = {
        "exit_code": 0,
        "result": {"candidate_count": 2, "safe_count": 2,
                   "already_applied_count": 0, "unsafe_count": 0},
    }
    app_root = _build_fake_app(tmp_path, preflight_payload=payload,
                               preflight_rc=0, apply_rc=4, proof_pack_rc=0)
    preflight_dir = tmp_path / "pf"
    res = _run_wrapper(app_root, preflight_dir)
    assert res.returncode == 0, res.stdout + res.stderr
    calls = _calls(app_root)
    assert any(c.startswith("apply --apply --confirm CUTOVER") for c in calls), calls
    assert any(c.startswith("verify ") for c in calls), calls
    assert any(c == "proof" for c in calls), calls
    assert "decision = apply" in res.stdout


def test_wrapper_aborts_before_apply_when_unsafe_present(tmp_path: Path):
    payload = {
        "exit_code": 1,
        "result": {"candidate_count": 2, "safe_count": 0,
                   "already_applied_count": 0, "unsafe_count": 2},
    }
    app_root = _build_fake_app(tmp_path, preflight_payload=payload,
                               preflight_rc=1)
    preflight_dir = tmp_path / "pf"
    res = _run_wrapper(app_root, preflight_dir)
    assert res.returncode != 0
    calls = _calls(app_root)
    # Apply, verify, proof must NOT have been invoked.
    assert not any(c.startswith("apply ") for c in calls), calls
    assert not any(c.startswith("verify ") for c in calls), calls
    assert not any(c == "proof" for c in calls), calls
    assert "REFUSING APPLY" in res.stdout


def test_wrapper_continues_to_verify_and_proof_after_skip_apply(tmp_path: Path):
    """Explicit assertion: when the wrapper decides to skip the apply
    step, it MUST still run the verifier and the proof pack so the
    operator gets the post-state output and a fresh match-rate snapshot.
    """
    payload = {
        "exit_code": 0,
        "result": {"candidate_count": 2, "safe_count": 0,
                   "already_applied_count": 2, "unsafe_count": 0},
    }
    app_root = _build_fake_app(tmp_path, preflight_payload=payload,
                               preflight_rc=0, verify_rc=0, proof_pack_rc=0)
    preflight_dir = tmp_path / "pf"
    res = _run_wrapper(app_root, preflight_dir)
    assert res.returncode == 0, res.stdout + res.stderr
    calls = _calls(app_root)
    verify_call = next(c for c in calls if c.startswith("verify "))
    assert "9391f78f-33c2-4186-9199-7df2da1124bb" in verify_call
    assert "5fe1d5c2-275c-4bbd-a693-6073a0fe9567" in verify_call
    assert any(c == "proof" for c in calls)
    # SUMMARY block is present and shows decision=skip_apply.
    assert "SUMMARY" in res.stdout
    assert "decision                : skip_apply" in res.stdout
    assert "apply_exit_code         : 0" in res.stdout
