"""HTTP fetching with a browser-like User-Agent, redirects, retries and a
local ``file://`` mode for testing against saved HTML.

Uses :mod:`requests` when importable and transparently falls back to
``urllib`` so the tool keeps working with only the standard library.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import urlparse, urlunparse, urljoin

try:  # pragma: no cover - exercised by import environment
    import requests  # type: ignore

    _HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    _HAVE_REQUESTS = False

import urllib.request
import urllib.error

# A modern desktop UA. Many CDNs reject the default library UA outright; a
# realistic UA gets us the same HTML a human browser would receive.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "AIShoppingReadinessAuditor/1.0"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class FetchResult:
    url: str
    ok: bool = False
    status: Optional[int] = None
    final_url: Optional[str] = None
    text: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    elapsed_ms: int = 0

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "ok": self.ok,
            "status": self.status,
            "final_url": self.final_url,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "bytes": len(self.text or ""),
        }


def normalize_url(url: str) -> str:
    """Add a scheme if missing and strip surrounding whitespace."""
    url = (url or "").strip()
    if not url:
        return url
    if url.startswith("file://"):
        return url
    parsed = urlparse(url)
    if not parsed.scheme:
        url = "https://" + url
        parsed = urlparse(url)
    # Drop fragments; they never reach the server.
    return urlunparse(parsed._replace(fragment=""))


def _classify_error(exc: Exception) -> str:
    name = type(exc).__name__
    msg = str(exc)
    if "timed out" in msg.lower() or "timeout" in name.lower():
        return "Request timed out — the page took too long to respond."
    if "ssl" in msg.lower():
        return f"SSL/TLS error: {msg}"
    if "name or service not known" in msg.lower() or "nodename" in msg.lower():
        return "DNS lookup failed — the domain could not be resolved."
    return f"{name}: {msg}"


def _fetch_file(url: str) -> FetchResult:
    path = url[len("file://"):]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        return FetchResult(url=url, ok=True, status=200, final_url=url, text=text)
    except OSError as exc:
        return FetchResult(url=url, ok=False, error=f"Cannot read local file: {exc}")


def fetch(url: str, timeout: int = 15, max_retries: int = 2) -> FetchResult:
    """Fetch ``url`` and return a :class:`FetchResult`.

    Retries transient network failures with exponential backoff. Recognises the
    sandbox egress-allowlist denial (``x-deny-reason: host_not_allowed``) and
    reports it in a way the UI can explain to the user.
    """
    url = normalize_url(url)
    if not url:
        return FetchResult(url=url, ok=False, error="Empty URL.")
    if url.startswith("file://"):
        return _fetch_file(url)

    last_error = "Unknown error"
    for attempt in range(max_retries + 1):
        start = time.time()
        try:
            if _HAVE_REQUESTS:
                resp = requests.get(
                    url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True
                )
                elapsed = int((time.time() - start) * 1000)
                headers = {k.lower(): v for k, v in resp.headers.items()}
                deny = headers.get("x-deny-reason")
                if deny:
                    return FetchResult(
                        url=url, ok=False, status=resp.status_code, headers=headers,
                        elapsed_ms=elapsed,
                        error=(
                            f"Blocked by network egress policy ({deny}). This host "
                            "is not on the environment allowlist — run the auditor "
                            "from a machine/environment with open egress, or add the "
                            "host to your egress settings."
                        ),
                    )
                text = resp.text
                ok = 200 <= resp.status_code < 400
                return FetchResult(
                    url=url, ok=ok, status=resp.status_code,
                    final_url=str(resp.url), text=text, headers=headers,
                    elapsed_ms=elapsed,
                    error=None if ok else f"HTTP {resp.status_code} {resp.reason}",
                )
            else:
                req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                    elapsed = int((time.time() - start) * 1000)
                    charset = resp.headers.get_content_charset() or "utf-8"
                    text = raw.decode(charset, errors="replace")
                    headers = {k.lower(): v for k, v in resp.headers.items()}
                    return FetchResult(
                        url=url, ok=True, status=resp.status,
                        final_url=resp.geturl(), text=text, headers=headers,
                        elapsed_ms=elapsed,
                    )
        except urllib.error.HTTPError as exc:  # pragma: no cover - urllib path
            elapsed = int((time.time() - start) * 1000)
            headers = {k.lower(): v for k, v in dict(exc.headers or {}).items()}
            deny = headers.get("x-deny-reason")
            err = (
                f"Blocked by network egress policy ({deny})."
                if deny else f"HTTP {exc.code} {exc.reason}"
            )
            return FetchResult(url=url, ok=False, status=exc.code, headers=headers,
                               elapsed_ms=elapsed, error=err)
        except Exception as exc:  # network-level error: retry
            last_error = _classify_error(exc)
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
    return FetchResult(url=url, ok=False, error=last_error)


def robots_url_for(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))


def absolute(base: str, maybe_relative: str) -> str:
    try:
        return urljoin(base, maybe_relative)
    except Exception:
        return maybe_relative
