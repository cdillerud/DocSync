"""
sharepoint_body_fetcher.py
==========================
Read-only SharePoint/Graph body fetcher used by
``document_body_reconciliation_probe.py``. Reuses the same
client-credentials Graph auth (TENANT_ID, GRAPH_CLIENT_ID,
GRAPH_CLIENT_SECRET) that ``sharepoint_ap_compare.acquire_graph_token``
already uses — no new env vars, no new auth flow.

Contract:
    fetcher(square9_row) -> (text: str, status: str)

Status values: ``ok`` / ``ocr_required`` / ``no_access``.

Behavior:
- Empty/missing ``square9_web_url`` -> ("", "no_access").
- Non-PDF binary (filename suffix .tif/.tiff/.png/.jpg/.jpeg/.gif/.bmp)
  -> ("", "ocr_required").
- PDF with >= 50 non-whitespace chars of extractable text -> ("text",
  "ok").
- PDF with < 50 non-whitespace chars (likely scanned)
  -> ("", "ocr_required").
- 30s hard timeout per file. Any HTTP error / network error / parse
  failure -> ("", "no_access"); never raises.
- Bytes cached at /tmp/body_probe_cache/<sha256>.bin (cache key is
  the SHA-256 of the web_url). Cache is bypassed when
  ``no_cache=True``.

The class is constructor-injected with a token provider and an HTTP
client factory so tests can run completely offline.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
from io import BytesIO
from typing import Any, Callable, Dict, Optional, Tuple


logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_CACHE_DIR = "/tmp/body_probe_cache"
MIN_NONWHITESPACE_CHARS = 50

OCR_REQUIRED_SUFFIXES = (
    ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".gif", ".bmp",
)

STATUS_OK = "ok"
STATUS_OCR = "ocr_required"
STATUS_NO_ACCESS = "no_access"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def url_to_share_id(web_url: str) -> str:
    """Microsoft Graph 'shares' encoding: u! + base64url, no padding."""
    raw = base64.b64encode(web_url.encode("utf-8")).decode("ascii")
    return "u!" + raw.rstrip("=").replace("/", "_").replace("+", "-")


def cache_key_for(web_url: str) -> str:
    return hashlib.sha256(web_url.encode("utf-8")).hexdigest()


def _is_image_or_tiff(web_url: str) -> bool:
    lower = web_url.lower()
    # Strip query string before checking extension.
    lower = lower.split("?", 1)[0]
    return any(lower.endswith(s) for s in OCR_REQUIRED_SUFFIXES)


def _nonwhitespace_count(s: str) -> int:
    return sum(1 for c in s if not c.isspace())


def _extract_pdf_text(data: bytes) -> str:
    """Extract embedded text from a PDF. Returns '' on parse failure."""
    try:
        import pypdf  # noqa: WPS433
    except ImportError:  # pragma: no cover
        return ""
    try:
        reader = pypdf.PdfReader(BytesIO(data))
        chunks = []
        for page in reader.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                continue
        return "\n".join(chunks)
    except Exception as e:  # noqa: BLE001
        logger.debug("pypdf parse failed: %s", e)
        return ""


def classify_bytes(data: bytes, web_url: str) -> Tuple[str, str]:
    """Pure decision: bytes + url -> (text, status). No I/O."""
    if _is_image_or_tiff(web_url):
        return "", STATUS_OCR
    text = _extract_pdf_text(data)
    if _nonwhitespace_count(text) >= MIN_NONWHITESPACE_CHARS:
        return text, STATUS_OK
    return "", STATUS_OCR


# ---------------------------------------------------------------------------
# Graph fetcher
# ---------------------------------------------------------------------------

# Type aliases for testability.
TokenProvider = Callable[[], str]
HttpClientFactory = Callable[[float], Any]  # (timeout) -> client


class GraphBodyFetcher:
    """Callable: fetcher(square9_row) -> (text, status)."""

    def __init__(self,
                 token_provider: TokenProvider,
                 http_client_factory: Optional[HttpClientFactory] = None,
                 cache_dir: str = DEFAULT_CACHE_DIR,
                 no_cache: bool = False,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 ):
        self._token_provider = token_provider
        self._http_client_factory = (
            http_client_factory or _default_http_client_factory)
        self._cache_dir = cache_dir
        self._no_cache = no_cache
        self._timeout = timeout

    # Pluggable token caching: re-using the email-poller's tokens is fine,
    # but we resolve once per fetcher instance and reuse for the whole probe.
    def _token(self) -> str:
        return self._token_provider()

    def _cache_path(self, web_url: str) -> str:
        return os.path.join(self._cache_dir, cache_key_for(web_url) + ".bin")

    def _read_cache(self, web_url: str) -> Optional[bytes]:
        try:
            path = self._cache_path(web_url)
            if not os.path.exists(path):
                return None
            with open(path, "rb") as f:
                return f.read()
        except OSError as e:
            logger.debug("cache read failed for %s: %s", web_url, e)
            return None

    def _write_cache(self, web_url: str, data: bytes) -> None:
        try:
            os.makedirs(self._cache_dir, exist_ok=True)
            tmp = self._cache_path(web_url) + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, self._cache_path(web_url))
        except OSError as e:
            logger.debug("cache write failed for %s: %s", web_url, e)

    def _fetch_bytes(self, web_url: str) -> Optional[bytes]:
        """Resolve the web_url via Graph 'shares' endpoint and download
        the file content. Returns None on any failure."""
        share_id = url_to_share_id(web_url)
        graph_url = f"{GRAPH_BASE}/shares/{share_id}/driveItem/content"
        try:
            token = self._token()
        except Exception as e:  # noqa: BLE001
            logger.warning("token acquisition failed: %s", e)
            return None
        try:
            with self._http_client_factory(self._timeout) as client:
                resp = client.get(
                    graph_url,
                    headers={"Authorization": f"Bearer {token}"},
                    follow_redirects=True,
                )
                status = getattr(resp, "status_code", 0)
                if status != 200:
                    logger.warning(
                        "graph fetch %s returned status=%s", web_url, status)
                    return None
                content = getattr(resp, "content", None)
                if content is None:
                    return None
                return content
        except Exception as e:  # noqa: BLE001
            logger.warning("graph fetch %s failed: %s", web_url, e)
            return None

    def __call__(self, row: Dict[str, str]) -> Tuple[str, str]:
        web_url = (row.get("square9_web_url") or "").strip()
        if not web_url:
            return "", STATUS_NO_ACCESS

        data: Optional[bytes] = None
        if not self._no_cache:
            data = self._read_cache(web_url)
        if data is None:
            data = self._fetch_bytes(web_url)
            if data is None:
                return "", STATUS_NO_ACCESS
            self._write_cache(web_url, data)
        return classify_bytes(data, web_url)


# ---------------------------------------------------------------------------
# Default http client factory (httpx). Tests inject their own.
# ---------------------------------------------------------------------------

def _default_http_client_factory(timeout: float):
    import httpx  # noqa: WPS433
    return httpx.Client(timeout=timeout)


# ---------------------------------------------------------------------------
# Glue: build the fetcher with the production token provider
# ---------------------------------------------------------------------------

def build_production_fetcher(no_cache: bool = False) -> GraphBodyFetcher:
    """Wire the same TENANT_ID / GRAPH_CLIENT_ID / GRAPH_CLIENT_SECRET
    flow used by ``sharepoint_ap_compare.acquire_graph_token``. No new
    env vars are introduced."""
    from scripts.sharepoint_ap_compare import acquire_graph_token

    tenant = os.environ.get("TENANT_ID", "")
    client_id = os.environ.get("GRAPH_CLIENT_ID", "")
    client_secret = os.environ.get("GRAPH_CLIENT_SECRET", "")

    cached_token: Dict[str, str] = {}

    def _provide() -> str:
        if "v" not in cached_token:
            cached_token["v"] = acquire_graph_token(
                tenant, client_id, client_secret)
        return cached_token["v"]

    return GraphBodyFetcher(token_provider=_provide, no_cache=no_cache)
