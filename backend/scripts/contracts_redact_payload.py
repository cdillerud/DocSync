"""Phase 3.2 — DocuSign payload redaction helper.

Takes a raw DocuSign Connect SIM payload (JSON) and produces a sanitized
copy suitable for committing as a regression fixture.

What gets redacted by default (deterministic, index-stable):
    * `name` / `userName` fields                → "Redacted Name 1", "Redacted Name 2", …
    * `email` fields                            → "redacted+1@example.com", …
    * `companyName` / `company` fields          → "Redacted Co 1", …
    * `accountId` / `userId`                    → "redacted-account-id", "redacted-user-id"
    * `documentBase64` / `pdfBytes`             → dropped entirely
    * `signerSecurityProtocol` and similar      → dropped (transport/auth metadata)

What is preserved:
    * Envelope structure
    * Recipient routing order, status, signing dates
    * `customFields[*].name` and value (use --extra-paths if values are sensitive)
    * `formData[*].name` and value (use --extra-paths if values are sensitive)
    * `envelopeDocuments[*].name` / mime / page / size
    * All status enums and dates

Usage:

    docker compose exec backend python -m scripts.contracts_redact_payload \\
        /tmp/connect_raw.json \\
        --extra-paths data.envelopeSummary.subject \\
        --extra-paths data.envelopeSummary.emailSubject \\
        > /tmp/connect_redacted.json

Use `-` for stdin / stdout pipelines.

The script prints a summary of what was redacted to stderr so you can audit
the diff before committing the fixture.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple


_DEFAULT_DROP_KEYS = {
    "documentBase64", "pdfBytes", "documentbase64",
    "signerSecurityProtocol", "signerSecurityCode",
    "tokenizedDocumentId",
}


# -----------------------------------------------------------------------
# Redactor — walks the JSON tree and replaces target keys with placeholders
# -----------------------------------------------------------------------

class _Redactor:

    def __init__(self) -> None:
        self.name_idx = 0
        self.email_idx = 0
        self.company_idx = 0
        self.name_map: Dict[str, str] = {}
        self.email_map: Dict[str, str] = {}
        self.company_map: Dict[str, str] = {}
        self.audit: List[Tuple[str, str, str]] = []  # (json_path, before, after)

    def _redact_name(self, path: str, original: str) -> str:
        if not isinstance(original, str) or not original.strip():
            return original
        if original in self.name_map:
            new = self.name_map[original]
        else:
            self.name_idx += 1
            new = f"Redacted Name {self.name_idx}"
            self.name_map[original] = new
        self.audit.append((path, original, new))
        return new

    def _redact_email(self, path: str, original: str) -> str:
        if not isinstance(original, str) or "@" not in original:
            return original
        if original in self.email_map:
            new = self.email_map[original]
        else:
            self.email_idx += 1
            new = f"redacted+{self.email_idx}@example.com"
            self.email_map[original] = new
        self.audit.append((path, original, new))
        return new

    def _redact_company(self, path: str, original: str) -> str:
        if not isinstance(original, str) or not original.strip():
            return original
        if original in self.company_map:
            new = self.company_map[original]
        else:
            self.company_idx += 1
            new = f"Redacted Co {self.company_idx}"
            self.company_map[original] = new
        self.audit.append((path, original, new))
        return new

    def _redact_scalar(
        self, path: str, key: str, value: Any,
    ) -> Tuple[bool, Any]:
        """Return (replaced?, new_value) for known-PII scalars.

        Note: `name` / `userName` / `companyName` are NOT handled here
        because they're context-sensitive (only person objects, never
        documents / customFields / formData). They're handled at the
        dict level in `walk()` once we can see sibling keys.
        """
        if not isinstance(value, str):
            return False, value
        kl = key.lower()
        if kl == "email":
            return True, self._redact_email(path, value)
        if kl == "accountid":
            self.audit.append((path, value, "redacted-account-id"))
            return True, "redacted-account-id"
        if kl == "userid":
            self.audit.append((path, value, "redacted-user-id"))
            return True, "redacted-user-id"
        return False, value

    @staticmethod
    def _looks_like_person_dict(d: Dict[str, Any]) -> bool:
        """Person blocks (sender / signer / cc) always carry an email field
        and at least one name-ish field. Documents / customFields / formData
        DO NOT carry email, so this disambiguates cleanly without parser-
        path heuristics.
        """
        if "email" not in d:
            return False
        for k in ("name", "userName", "fullName", "displayName", "companyName"):
            if k in d:
                return True
        return False

    def walk(self, node: Any, path: str = "") -> Any:
        if isinstance(node, dict):
            person = self._looks_like_person_dict(node)
            out: Dict[str, Any] = {}
            for k, v in node.items():
                child_path = f"{path}.{k}" if path else k
                if k in _DEFAULT_DROP_KEYS:
                    self.audit.append((child_path, "<dropped>", "<dropped>"))
                    continue
                # Person-scoped redaction of name / companyName.
                if person and isinstance(v, str):
                    kl = k.lower()
                    if kl in ("name", "username", "fullname", "displayname"):
                        out[k] = self._redact_name(child_path, v)
                        continue
                    if kl in ("companyname", "company"):
                        out[k] = self._redact_company(child_path, v)
                        continue
                replaced, replacement = self._redact_scalar(child_path, k, v)
                if replaced:
                    out[k] = replacement
                else:
                    out[k] = self.walk(v, child_path)
            return out
        if isinstance(node, list):
            return [self.walk(item, f"{path}[{i}]") for i, item in enumerate(node)]
        return node


# -----------------------------------------------------------------------
# JSON-path utilities for --extra-paths and --keep-paths
# -----------------------------------------------------------------------

_INDEX_RE = re.compile(r"^\[(\d+)\]$")


def _split_path(path: str) -> List[str]:
    """Split a dotted JSON path with optional [n] index segments.
    e.g. 'data.envelopeSummary.recipients.signers[0].name'
         → ['data','envelopeSummary','recipients','signers','[0]','name']
    """
    out: List[str] = []
    for part in path.split("."):
        m = re.match(r"^([^\[\]]+)((?:\[\d+\])*)$", part)
        if not m:
            out.append(part)
            continue
        if m.group(1):
            out.append(m.group(1))
        for idx in re.findall(r"\[(\d+)\]", m.group(2) or ""):
            out.append(f"[{idx}]")
    return out


def _redact_extra_path(doc: Any, path: str, redactor: _Redactor) -> None:
    parts = _split_path(path)
    parents = [doc]
    cursor: Any = doc
    accessor: Any = None
    for part in parts:
        m = _INDEX_RE.match(part)
        if isinstance(cursor, list) and m:
            idx = int(m.group(1))
            if idx >= len(cursor):
                return
            accessor = idx
            parents.append(cursor)
            cursor = cursor[idx]
        elif isinstance(cursor, dict):
            if part not in cursor:
                return
            accessor = part
            parents.append(cursor)
            cursor = cursor[part]
        else:
            return
    parent = parents[-1]
    if isinstance(cursor, str):
        replacement = f"redacted::{path}"
        redactor.audit.append((path, cursor, replacement))
        if isinstance(parent, list):
            parent[accessor] = replacement
        else:
            parent[accessor] = replacement


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------

def _load(arg: str) -> Any:
    if arg == "-":
        return json.loads(sys.stdin.read() or "null")
    with open(arg, "r", encoding="utf-8") as fp:
        return json.load(fp)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Path to raw payload JSON, or '-' for stdin")
    parser.add_argument("--output", "-o", default="-",
                        help="Path to write redacted JSON, or '-' for stdout (default)")
    parser.add_argument("--extra-paths", action="append", default=[],
                        metavar="JSON_PATH",
                        help="Additional dotted JSON paths to redact (repeatable). "
                             "Example: data.envelopeSummary.subject")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress redaction-summary stderr output")
    args = parser.parse_args()

    try:
        payload = _load(args.input)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR reading input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("ERROR: top-level payload must be a JSON object", file=sys.stderr)
        return 2

    redactor = _Redactor()
    redacted = redactor.walk(copy.deepcopy(payload))
    for extra in args.extra_paths:
        _redact_extra_path(redacted, extra, redactor)

    out_text = json.dumps(redacted, indent=2, sort_keys=False, default=str)
    if args.output == "-":
        sys.stdout.write(out_text + "\n")
    else:
        with open(args.output, "w", encoding="utf-8") as fp:
            fp.write(out_text + "\n")

    if not args.quiet:
        print(f"redacted {len(redactor.audit)} fields:", file=sys.stderr)
        for path, before, after in redactor.audit[:50]:
            short_before = (before if len(before) <= 30 else before[:27] + "…")
            print(f"  {path}: {short_before!r} → {after!r}", file=sys.stderr)
        if len(redactor.audit) > 50:
            print(f"  … and {len(redactor.audit) - 50} more", file=sys.stderr)
        print(
            f"placeholder counts: names={redactor.name_idx} "
            f"emails={redactor.email_idx} companies={redactor.company_idx}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
