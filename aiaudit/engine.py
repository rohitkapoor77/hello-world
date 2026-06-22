"""Audit orchestration: fetch a URL, read robots.txt, extract structured data,
score it, and assemble a JSON-serialisable report. Includes a concurrent batch
runner for up to :data:`aiaudit.MAX_URLS` URLs.
"""
from __future__ import annotations

import concurrent.futures
import datetime as _dt
from typing import Dict, List, Optional

from . import MAX_URLS
from .fetcher import fetch, normalize_url
from .robots import check_robots
from .schema import extract_profile
from .scoring import evaluate, summarize


def audit_url(url: str, *, robots_text: Optional[str] = None,
              html: Optional[str] = None) -> dict:
    """Audit a single URL and return the full report dict.

    ``html``/``robots_text`` can be injected to audit pre-fetched content
    (used by tests and the local ``file://`` path).
    """
    url = normalize_url(url)
    if html is not None:
        from .fetcher import FetchResult
        fetch_result = FetchResult(url=url, ok=True, status=200, final_url=url, text=html)
    else:
        fetch_result = fetch(url)

    profile = extract_profile(fetch_result.text) if fetch_result.ok else extract_profile("")

    robots_result = check_robots(url, robots_text=robots_text)

    checks = evaluate(profile, robots_result, fetch_result)
    summary = summarize(checks)

    top_missing = [c.label for c in sorted(checks, key=lambda c: -c.lost)
                   if c.status in ("fail", "partial")][:3]

    return {
        "url": url,
        "final_url": fetch_result.final_url or url,
        "fetched_ok": fetch_result.ok,
        "http_status": fetch_result.status,
        "error": fetch_result.error,
        "elapsed_ms": fetch_result.elapsed_ms,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "score": summary["score"],
        "band": summary["band"],
        "band_label": summary["band_label"],
        "earned": summary["earned"],
        "possible": summary["possible"],
        "categories": summary["categories"],
        "fixes": summary["fixes"],
        "top_missing": top_missing,
        "checks": [c.as_dict() for c in checks],
        "product": profile.as_dict() if fetch_result.ok else {"fields": {}, "meta": {}},
        "robots": robots_result.as_dict(),
    }


def audit_batch(urls: List[str], *, max_workers: int = 8,
                progress=None) -> List[dict]:
    """Audit many URLs concurrently. Deduplicates and caps at MAX_URLS."""
    seen = set()
    cleaned: List[str] = []
    for u in urls:
        nu = normalize_url(u)
        if not nu or nu in seen:
            continue
        seen.add(nu)
        cleaned.append(nu)
        if len(cleaned) >= MAX_URLS:
            break

    results: Dict[str, dict] = {}
    if not cleaned:
        return []

    workers = max(1, min(max_workers, len(cleaned)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(audit_url, u): u for u in cleaned}
        done = 0
        for fut in concurrent.futures.as_completed(future_map):
            u = future_map[fut]
            try:
                results[u] = fut.result()
            except Exception as exc:  # never let one URL kill the batch
                results[u] = _error_result(u, f"Audit failed: {exc}")
            done += 1
            if progress:
                progress(done, len(cleaned))

    # preserve input order
    return [results[u] for u in cleaned]


def _error_result(url: str, message: str) -> dict:
    return {
        "url": url, "final_url": url, "fetched_ok": False, "http_status": None,
        "error": message, "score": 0, "band": "not_ready", "band_label": "Not Ready",
        "categories": [], "fixes": [], "top_missing": [message], "checks": [],
        "product": {"fields": {}, "meta": {}}, "robots": {},
    }


def batch_summary(results: List[dict]) -> dict:
    """Dashboard rollup across a batch of audit results."""
    n = len(results)
    ready = sum(1 for r in results if r.get("band") == "ready")
    partial = sum(1 for r in results if r.get("band") == "partial")
    not_ready = sum(1 for r in results if r.get("band") == "not_ready")
    scores = [r.get("score", 0) for r in results]
    avg = round(sum(scores) / n) if n else 0
    return {
        "count": n, "ready": ready, "partial": partial, "not_ready": not_ready,
        "avg_score": avg,
        "best": max(scores) if scores else 0,
        "worst": min(scores) if scores else 0,
    }
