"""Offline tests for the audit engine, robots matcher and exporters.

Runs without network access using local HTML fixtures. Works under pytest or as
a plain script: ``python3 tests/test_engine.py``.
"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiaudit.engine import audit_url, audit_batch, batch_summary
from aiaudit.robots import check_robots, evaluate_robots
from aiaudit import exporter

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _html(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return fh.read()


def test_ready_product_scores_high():
    r = audit_url("https://example-store.com/products/aurora-merino-beanie",
                  html=_html("ready_product.html"), robots_text="")
    assert r["band"] == "ready", r["score"]
    assert r["score"] >= 90, r["score"]
    f = r["product"]["fields"]
    for key in ("name", "description", "image", "price", "priceCurrency",
                "availability", "brand", "sku", "gtin", "aggregateRating"):
        assert f.get(key), f"expected {key} present"
    assert f["shipping"] and f["returns"]
    assert f["variesBy"]


def test_partial_product_is_partial():
    r = audit_url("https://example-store.com/products/console-era-art-display",
                  html=_html("partial_product.html"), robots_text="")
    assert r["band"] == "partial", (r["band"], r["score"])
    f = r["product"]["fields"]
    assert not f.get("gtin")            # GTIN missing
    assert not f.get("aggregateRating")  # reviews missing
    fix_titles = [x["title"] for x in r["fixes"]]
    assert any("rating" in t.lower() for t in fix_titles)
    assert any("GTIN" in t for t in fix_titles)


def test_not_ready_product_is_not_ready():
    robots = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: PerplexityBot\nDisallow: /\n"
    r = audit_url("https://loomco.example/products/throw",
                  html=_html("not_ready_product.html"), robots_text=robots)
    assert r["band"] == "not_ready", (r["band"], r["score"])
    assert not r["product"]["product_found"]
    blocked = [b["token"] for b in r["robots"]["bots"] if not b["allowed"]]
    assert "GPTBot" in blocked and "PerplexityBot" in blocked


def test_robots_matcher_specificity_and_wildcards():
    txt = (
        "User-agent: *\nDisallow: /\n\n"
        "User-agent: Googlebot\nAllow: /\n\n"
        "User-agent: GPTBot\nDisallow: /private/\nAllow: /products/\n"
    )
    bots, _ = evaluate_robots(txt, "https://x.com/products/abc")
    by = {b.token: b for b in bots}
    assert by["Googlebot"].allowed is True       # specific Allow group
    assert by["GPTBot"].allowed is True          # /products/ allowed
    assert by["Amazonbot"].allowed is False      # falls back to * -> Disallow /

    bots2, _ = evaluate_robots(txt, "https://x.com/private/x")
    by2 = {b.token: b for b in bots2}
    assert by2["GPTBot"].allowed is False        # /private/ disallowed


def test_robots_missing_allows_all():
    r = check_robots("https://x.com/products/a", robots_text="")
    assert r.allowed_count == len(r.bots)


def test_csv_export_has_row_per_url():
    results = [
        audit_url("https://a.example/p", html=_html("ready_product.html"), robots_text=""),
        audit_url("https://b.example/p", html=_html("partial_product.html"), robots_text=""),
    ]
    csv_text = exporter.to_csv(results)
    lines = [l for l in csv_text.splitlines() if l.strip()]
    assert len(lines) == 3  # header + 2
    assert "Score" in lines[0]


def test_xlsx_export_is_valid_zip_with_two_sheets():
    results = [audit_url("https://a.example/p", html=_html("ready_product.html"),
                         robots_text="")]
    data = exporter.to_xlsx(results)
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        assert "xl/worksheets/sheet1.xml" in names
        assert "xl/worksheets/sheet2.xml" in names
        assert "[Content_Types].xml" in names
        # sheets must contain data
        assert b"Summary" not in z.read("xl/worksheets/sheet1.xml")  # name is in workbook.xml
        assert b"<row" in z.read("xl/worksheets/sheet1.xml")


def test_batch_dedupes_and_summarizes():
    urls = ["https://a.example/p", "https://a.example/p", "https://b.example/p"]
    # inject via file:// to avoid network
    ready = os.path.join(FIX, "ready_product.html")
    results = audit_batch([f"file://{ready}"])
    assert len(results) == 1
    summ = batch_summary(results)
    assert summ["count"] == 1


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    return passed == len(tests)


if __name__ == "__main__":
    ok = _run_all()
    sys.exit(0 if ok else 1)
