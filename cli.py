#!/usr/bin/env python3
"""Command-line batch auditor.

    python cli.py https://store.com/products/a https://store.com/products/b
    python cli.py --file urls.txt
    python cli.py --file urls.txt --csv report.csv
    python cli.py --file urls.txt --xlsx report.xlsx --json report.json

Reads up to 25 URLs (from arguments and/or a file, one per line), audits them
concurrently and prints a readiness summary. Optionally writes CSV / XLSX / JSON.
"""
import argparse
import json
import sys

from aiaudit import MAX_URLS, exporter
from aiaudit.engine import audit_batch, batch_summary

BANDS = {"ready": "READY    ", "partial": "PARTIAL  ", "not_ready": "NOT READY"}


def _load_file(path):
    with open(path, encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()
                and not line.strip().startswith("#")]


def main():
    ap = argparse.ArgumentParser(description="AI Shopping Readiness Auditor — CLI")
    ap.add_argument("urls", nargs="*", help="Product page URLs")
    ap.add_argument("--file", "-f", help="File with one URL per line")
    ap.add_argument("--csv", help="Write summary CSV to this path")
    ap.add_argument("--checks-csv", help="Write per-check CSV to this path")
    ap.add_argument("--xlsx", help="Write .xlsx workbook to this path")
    ap.add_argument("--json", help="Write full results JSON to this path")
    ap.add_argument("--workers", type=int, default=8, help="Concurrent fetches")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.file:
        urls += _load_file(args.file)
    urls = [u for u in urls if u]
    if not urls:
        ap.error("Provide URLs as arguments or via --file.")
    if len(urls) > MAX_URLS:
        print(f"Note: {len(urls)} URLs given; auditing the first {MAX_URLS}.",
              file=sys.stderr)

    def progress(done, total):
        print(f"\r  Auditing… {done}/{total}", end="", file=sys.stderr, flush=True)

    results = audit_batch(urls, max_workers=args.workers, progress=progress)
    print("\r" + " " * 30 + "\r", end="", file=sys.stderr)

    summ = batch_summary(results)
    print()
    print(f"  {'SCORE':>5}  {'STATUS':<9}  {'ROBOTS':>6}  URL")
    print("  " + "-" * 78)
    for r in results:
        robots = r.get("robots", {})
        pct = robots.get("access_ratio")
        pct_s = f"{round(pct*100)}%" if pct is not None else "  -"
        band = BANDS.get(r.get("band"), r.get("band", ""))
        print(f"  {r['score']:>5}  {band}  {pct_s:>6}  {r['url']}")
    print("  " + "-" * 78)
    print(f"  {summ['count']} pages · avg {summ['avg_score']} · "
          f"{summ['ready']} ready / {summ['partial']} partial / "
          f"{summ['not_ready']} not ready")
    print()

    if args.csv:
        with open(args.csv, "w", encoding="utf-8", newline="") as fh:
            fh.write(exporter.to_csv(results))
        print(f"  Wrote summary CSV  -> {args.csv}")
    if args.checks_csv:
        with open(args.checks_csv, "w", encoding="utf-8", newline="") as fh:
            fh.write(exporter.to_checks_csv(results))
        print(f"  Wrote checks CSV   -> {args.checks_csv}")
    if args.xlsx:
        with open(args.xlsx, "wb") as fh:
            fh.write(exporter.to_xlsx(results))
        print(f"  Wrote Excel xlsx   -> {args.xlsx}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"results": results, "summary": summ}, fh, indent=2)
        print(f"  Wrote JSON         -> {args.json}")

    # Exit non-zero if nothing is ready (handy for CI gates).
    return 0 if summ["ready"] == summ["count"] else 0


if __name__ == "__main__":
    sys.exit(main())
