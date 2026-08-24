from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field


APP_VERSION = "0.41.0"
EXPECTED_ENVIRONMENT = "Sandbox_NoZetadocs_UAT"
PROTECTED_QUOTES = {67}

ACTION_VALUES = (
    "evaluate",
    "readyForReview",
    "approve",
    "reject",
    "reopen",
)

ActionName = Literal[
    "evaluate",
    "readyForReview",
    "approve",
    "reject",
    "reopen",
]


BASE_DIR = Path(__file__).resolve().parent
APP_ROOT = BASE_DIR.parent
SCRIPT_DIR = APP_ROOT / "scripts"

FLOW_SCRIPT = (
    SCRIPT_DIR
    / "Invoke-GPIPackagingQuoteCopilotFlowUAT.ps1"
)

OPENAPI_CONTRACT = (
    APP_ROOT
    / "copilot"
    / "GPI-PackagingQuoteAction.openapi.json"
)


def execute_enabled() -> bool:
    return (
        os.getenv("GPI_ENABLE_COPILOT_EXECUTE", "0")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )


def find_powershell() -> str:
    for candidate in ("pwsh.exe", "pwsh", "powershell.exe", "powershell"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    raise RuntimeError(
        "PowerShell executable was not found."
    )


def validate_runtime_files() -> None:
    if not FLOW_SCRIPT.is_file():
        raise RuntimeError(
            f"0.39 flow script not found: {FLOW_SCRIPT}"
        )

    if not OPENAPI_CONTRACT.is_file():
        raise RuntimeError(
            f"0.40 OpenAPI contract not found: {OPENAPI_CONTRACT}"
        )


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quoteNo: int = Field(ge=1)
    action: ActionName


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quoteNo: int = Field(ge=1)
    action: ActionName
    confirmationToken: str = Field(min_length=1)


class ErrorBody(BaseModel):
    error: str
    message: str
    quoteNo: int | None = None
    action: str | None = None
    retryPrepare: bool = False


app = FastAPI(
    title="GPI Packaging Quote Copilot Actions",
    version=APP_VERSION,
    description=(
        "Local UAT HTTP adapter for the validated GPI Packaging Quote "
        "Copilot action flow."
    ),
)


def protected_quote_guard(quote_no: int) -> None:
    if quote_no in PROTECTED_QUOTES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "protected_quote",
                "message": (
                    f"Packaging Quote {quote_no} is protected "
                    "and may not be used by this adapter."
                ),
                "quoteNo": quote_no,
                "retryPrepare": False,
            },
        )


def classify_flow_error(
    message: str,
    quote_no: int,
    action: str,
) -> HTTPException:
    normalized = message.lower()

    if (
        "confirmation token does not match" in normalized
        or "not currently allowed" in normalized
        or "became unavailable" in normalized
        or "current live quote/action state" in normalized
    ):
        status_code = 409
        error = "state_conflict"
        retry_prepare = True

    elif (
        "requires the confirmation token" in normalized
        or "protected" in normalized
        or "uat-only" in normalized
    ):
        status_code = 400
        error = "invalid_request"
        retry_prepare = False

    else:
        status_code = 500
        error = "integration_failure"
        retry_prepare = False

    return HTTPException(
        status_code=status_code,
        detail={
            "error": error,
            "message": message,
            "quoteNo": quote_no,
            "action": action,
            "retryPrepare": retry_prepare,
        },
    )


def invoke_flow(
    *,
    mode: Literal["Prepare", "Execute"],
    quote_no: int,
    action: ActionName,
    confirmation_token: str | None = None,
) -> dict:
    validate_runtime_files()

    powershell = find_powershell()

    # Write-Host uses PowerShell's Information stream.
    # Redirect stream 6 to null so the HTTP adapter receives only the
    # JSON payload emitted by the 0.39 wrapper on the success stream.
    ps = [
        "$ErrorActionPreference = 'Stop'",
        f"$flow = '{str(FLOW_SCRIPT).replace(chr(39), chr(39) * 2)}'",
        "$p = @{",
        f"  Mode = '{mode}'",
        f"  QuoteNo = {quote_no}",
        f"  Action = '{action}'",
        "  OutputFormat = 'Json'",
        "}",
    ]

    if confirmation_token is not None:
        escaped = confirmation_token.replace("'", "''")
        ps.append(
            f"$p.ConfirmationToken = '{escaped}'"
        )

    ps.extend(
        [
            "$json = & $flow @p 6>$null",
            "if ($null -eq $json) {",
            "  throw 'STOP: flow returned no JSON payload.'",
            "}",
            "$json | Out-String -Width 100000",
        ]
    )

    command = "\n".join(ps)

    completed = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=str(APP_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if completed.returncode != 0:
        message = stderr or stdout or (
            f"PowerShell flow exited with code "
            f"{completed.returncode}."
        )

        # Keep the user-facing failure concise while preserving the
        # original STOP reason when PowerShell includes formatting.
        stop_index = message.find("STOP:")
        if stop_index >= 0:
            message = message[stop_index:].strip()

        raise classify_flow_error(
            message=message,
            quote_no=quote_no,
            action=action,
        )

    if not stdout:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "empty_flow_response",
                "message": "0.39 flow returned an empty response.",
                "quoteNo": quote_no,
                "action": action,
                "retryPrepare": False,
            },
        )

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "invalid_flow_json",
                "message": (
                    "0.39 flow did not return valid JSON: "
                    f"{exc}"
                ),
                "quoteNo": quote_no,
                "action": action,
                "retryPrepare": False,
            },
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=500,
            detail={
                "error": "invalid_flow_shape",
                "message": (
                    "0.39 flow returned JSON that was not an object."
                ),
                "quoteNo": quote_no,
                "action": action,
                "retryPrepare": False,
            },
        )

    return payload


@app.get("/health")
def health() -> dict:
    validate_runtime_files()

    return {
        "status": "ok",
        "version": APP_VERSION,
        "environment": EXPECTED_ENVIRONMENT,
        "executeEnabled": execute_enabled(),
        "flowScript": FLOW_SCRIPT.name,
        "openApiContract": OPENAPI_CONTRACT.name,
    }


@app.post("/packagingQuoteActions/prepare")
def prepare_action(request: PrepareRequest) -> dict:
    protected_quote_guard(request.quoteNo)

    return invoke_flow(
        mode="Prepare",
        quote_no=request.quoteNo,
        action=request.action,
    )


@app.post("/packagingQuoteActions/execute")
def execute_action(request: ExecuteRequest) -> dict:
    protected_quote_guard(request.quoteNo)

    if not execute_enabled():
        raise HTTPException(
            status_code=403,
            detail={
                "error": "execute_disabled",
                "message": (
                    "Execute is disabled for the 0.41 local UAT "
                    "acceptance phase. Set "
                    "GPI_ENABLE_COPILOT_EXECUTE=1 only for a "
                    "deliberately authorized write test."
                ),
                "quoteNo": request.quoteNo,
                "action": request.action,
                "retryPrepare": False,
            },
        )

    return invoke_flow(
        mode="Execute",
        quote_no=request.quoteNo,
        action=request.action,
        confirmation_token=request.confirmationToken,
    )