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

# Failure reason detail buckets recorded on the fetcher's
# ``last_diagnostic`` after each call. Successful fetches use "ok";
# OCR-required (image/scanned) fetches use "ocr_required".
DETAIL_OK = "ok"
DETAIL_OCR_REQUIRED = "ocr_required"
DETAIL_EMPTY_URL = "empty_url"
DETAIL_UNSUPPORTED_URL_SCHEME = "unsupported_url_scheme"
DETAIL_TOKEN_ERROR = "token_error"
DETAIL_TIMEOUT = "timeout"
DETAIL_NETWORK_ERROR = "network_error"
DETAIL_HTTP_400_RESOLVE_FAILED = "graph_resolve_failed"
DETAIL_HTTP_403 = "http_403"
DETAIL_HTTP_404 = "http_404"
DETAIL_HTTP_429 = "http_429"
DETAIL_DOWNLOAD_FAILED = "download_failed"
DETAIL_UNKNOWN_ERROR = "unknown_error"


def _http_other(status: int) -> str:
    return f"http_other_{int(status)}"


_URL_SCHEME_RE = re.compile(r"^https?://", re.I)


def _classify_exception(e: BaseException) -> str:
    name = type(e).__name__.lower()
    if "timeout" in name:
        return DETAIL_TIMEOUT
    if any(k in name for k in (
            "connect", "network", "remoteprotocol", "transport",
            "readerror", "writeerror", "proxyerror", "dnserror")):
        return DETAIL_NETWORK_ERROR
    return DETAIL_UNKNOWN_ERROR


def _truncate_body(b: Any, limit: int = 500) -> str:
    if b is None:
        return ""
    try:
        if isinstance(b, bytes):
            text = b.decode("utf-8", errors="replace")
        else:
            text = str(b)
    except Exception:  # noqa: BLE001
        return ""
    text = text.strip()
    if len(text) > limit:
        return text[:limit] + f"... (+{len(text) - limit} chars)"
    return text


def _fresh_diag() -> Dict[str, Any]:
    return {
        "graph_url": "",
        "http_status": None,
        "failure_reason_detail": None,
        "error_body_snippet": "",
        "exception_class": "",
        "exception_message": "",
    }


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
        # Per-call diagnostic. Reset on each __call__.
        self.last_diagnostic: Dict[str, Any] = _fresh_diag()

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
        the file content. Returns None on any failure. Records details
        on ``self.last_diagnostic``."""
        share_id = url_to_share_id(web_url)
        graph_url = f"{GRAPH_BASE}/shares/{share_id}/driveItem/content"
        self.last_diagnostic["graph_url"] = graph_url
        try:
            token = self._token()
        except Exception as e:  # noqa: BLE001
            logger.warning("token acquisition failed: %s", e)
            self.last_diagnostic["failure_reason_detail"] = DETAIL_TOKEN_ERROR
            self.last_diagnostic["exception_class"] = type(e).__name__
            self.last_diagnostic["exception_message"] = str(e)
            return None
        try:
            with self._http_client_factory(self._timeout) as client:
                resp = client.get(
                    graph_url,
                    headers={"Authorization": f"Bearer {token}"},
                    follow_redirects=True,
                )
                status = getattr(resp, "status_code", 0)
                self.last_diagnostic["http_status"] = status
                if status != 200:
                    self.last_diagnostic["error_body_snippet"] = (
                        _truncate_body(getattr(resp, "content", None)))
                    if status == 400:
                        detail = DETAIL_HTTP_400_RESOLVE_FAILED
                    elif status == 403:
                        detail = DETAIL_HTTP_403
                    elif status == 404:
                        detail = DETAIL_HTTP_404
                    elif status == 429:
                        detail = DETAIL_HTTP_429
                    else:
                        detail = _http_other(status)
                    self.last_diagnostic["failure_reason_detail"] = detail
                    logger.warning(
                        "graph fetch %s returned status=%s detail=%s",
                        web_url, status, detail)
                    return None
                content = getattr(resp, "content", None)
                if content is None:
                    self.last_diagnostic["failure_reason_detail"] = (
                        DETAIL_DOWNLOAD_FAILED)
                    return None
                return content
        except Exception as e:  # noqa: BLE001
            logger.warning("graph fetch %s failed: %s", web_url, e)
            self.last_diagnostic["failure_reason_detail"] = (
                _classify_exception(e))
            self.last_diagnostic["exception_class"] = type(e).__name__
            self.last_diagnostic["exception_message"] = str(e)
            return None

    def __call__(self, row: Dict[str, str]) -> Tuple[str, str]:
        # Reset diagnostics for this call so callers always see this
        # row's outcome (not a previous row's).
        self.last_diagnostic = _fresh_diag()

        web_url = (row.get("square9_web_url") or "").strip()
        if not web_url:
            self.last_diagnostic["failure_reason_detail"] = DETAIL_EMPTY_URL
            return "", STATUS_NO_ACCESS
        if not _URL_SCHEME_RE.match(web_url):
            self.last_diagnostic["failure_reason_detail"] = (
                DETAIL_UNSUPPORTED_URL_SCHEME)
            return "", STATUS_NO_ACCESS

        data: Optional[bytes] = None
        cache_hit = False
        if not self._no_cache:
            data = self._read_cache(web_url)
            if data is not None:
                cache_hit = True
        if data is None:
            data = self._fetch_bytes(web_url)
            if data is None:
                # _fetch_bytes already set failure_reason_detail.
                if not self.last_diagnostic.get("failure_reason_detail"):
                    self.last_diagnostic["failure_reason_detail"] = (
                        DETAIL_UNKNOWN_ERROR)
                return "", STATUS_NO_ACCESS
            self._write_cache(web_url, data)
        elif cache_hit:
            # Even on a cache hit we want the graph_url field populated
            # so diagnostics are consistent.
            self.last_diagnostic["graph_url"] = (
                f"{GRAPH_BASE}/shares/{url_to_share_id(web_url)}"
                f"/driveItem/content")
            self.last_diagnostic["http_status"] = "cache_hit"

        text, status = classify_bytes(data, web_url)
        self.last_diagnostic["failure_reason_detail"] = (
            DETAIL_OK if status == STATUS_OK else DETAIL_OCR_REQUIRED)
        return text, status


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
