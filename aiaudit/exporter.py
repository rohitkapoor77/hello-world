"""Export audit results to CSV or a real .xlsx workbook.

The XLSX writer is written against the Office Open XML spec using only
``zipfile`` from the standard library (inline strings, one bold header style),
so no third-party packages are required.
"""
from __future__ import annotations

import csv
import io
import zipfile
from typing import Any, List
from xml.sax.saxutils import escape

SUMMARY_HEADERS = [
    "URL", "Final URL", "HTTP Status", "Score", "Readiness", "Reachable",
    "Robots AI Access %", "Blocked Crawlers", "Has JSON-LD", "Product Schema",
    "Name", "Description", "Image(s)", "Price", "Currency", "Availability",
    "Brand", "SKU/MPN", "GTIN", "Aggregate Rating", "Reviews", "Shipping",
    "Returns", "Total Fixes", "Top Fix 1", "Top Fix 2", "Top Fix 3",
]

CHECK_HEADERS = [
    "URL", "Category", "Check", "Status", "Earned", "Possible", "Priority",
    "Evidence", "Recommendation",
]


def _yn(v: Any) -> str:
    return "Yes" if v else "No"


def _summary_row(r: dict) -> list:
    product = r.get("product", {}) or {}
    fields = product.get("fields", {}) or {}
    robots = r.get("robots", {}) or {}
    fixes = r.get("fixes", []) or []
    top = [(fixes[i]["title"] if i < len(fixes) else "") for i in range(3)]
    blocked = [b["token"] for b in robots.get("bots", []) if not b.get("allowed")]

    gtin = fields.get("gtin")
    if not gtin and fields.get("identifier_exists_false"):
        gtin = "identifier_exists=false"

    access_pct = ""
    if robots and robots.get("access_ratio") is not None:
        access_pct = round(robots["access_ratio"] * 100)

    return [
        r.get("url", ""), r.get("final_url", ""), r.get("http_status", ""),
        r.get("score", 0), r.get("band_label", ""), _yn(r.get("fetched_ok")),
        access_pct, ", ".join(blocked),
        _yn(product.get("has_jsonld")), _yn(product.get("product_found")),
        fields.get("name") or "", _yn(fields.get("description")),
        fields.get("image_count") or 0, fields.get("price") or "",
        fields.get("priceCurrency") or "", fields.get("availability") or "",
        fields.get("brand") or "", fields.get("sku") or fields.get("mpn") or "",
        gtin or "", fields.get("aggregateRating") or "",
        fields.get("review_nodes") or 0, _yn(fields.get("shipping")),
        _yn(fields.get("returns")), len(fixes), top[0], top[1], top[2],
    ]


def to_csv(results: List[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(SUMMARY_HEADERS)
    for r in results:
        writer.writerow(_summary_row(r))
    return buf.getvalue()


def to_checks_csv(results: List[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CHECK_HEADERS)
    for r in results:
        for c in r.get("checks", []):
            writer.writerow([
                r.get("url", ""), c.get("category_label", c.get("category", "")),
                c.get("label", ""), c.get("status", ""), c.get("earned", ""),
                c.get("possible", ""), c.get("priority", ""),
                c.get("evidence", ""), c.get("fix", ""),
            ])
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Minimal XLSX writer
# --------------------------------------------------------------------------- #

def _col_letter(idx: int) -> str:
    """0-based column index -> Excel column letters (A, B, ... AA)."""
    letters = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _cell(ref: str, value: Any, bold: bool = False) -> str:
    style = ' s="1"' if bold else ""
    if value is None or value == "":
        return f'<c r="{ref}"{style}/>'
    if isinstance(value, bool):
        value = "Yes" if value else "No"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{style}><v>{value}</v></c>'
    text = escape(str(value))
    return (f'<c r="{ref}"{style} t="inlineStr">'
            f'<is><t xml:space="preserve">{text}</t></is></c>')


def _sheet_xml(rows: List[list]) -> str:
    n_rows = len(rows)
    n_cols = max((len(r) for r in rows), default=1)
    dim = f"A1:{_col_letter(n_cols - 1)}{max(n_rows, 1)}"
    out = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        f'<dimension ref="{dim}"/>',
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>',
        '<sheetData>',
    ]
    for ri, row in enumerate(rows, start=1):
        out.append(f'<row r="{ri}">')
        for ci, val in enumerate(row):
            ref = f"{_col_letter(ci)}{ri}"
            out.append(_cell(ref, val, bold=(ri == 1)))
        out.append('</row>')
    out.append('</sheetData></worksheet>')
    return "".join(out)


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '</Types>'
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>'
)

_WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets>'
    '<sheet name="Summary" sheetId="1" r:id="rId1"/>'
    '<sheet name="Checks" sheetId="2" r:id="rId2"/>'
    '</sheets></workbook>'
)

_WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '</Relationships>'
)

# Two fonts (normal, bold); header cells reference cellXfs index 1.
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2">'
    '<font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font>'
    '</fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>'
)


def to_xlsx(results: List[dict]) -> bytes:
    summary_rows = [SUMMARY_HEADERS] + [_summary_row(r) for r in results]
    check_rows = [CHECK_HEADERS]
    for r in results:
        for c in r.get("checks", []):
            check_rows.append([
                r.get("url", ""), c.get("category_label", c.get("category", "")),
                c.get("label", ""), c.get("status", ""), c.get("earned", ""),
                c.get("possible", ""), c.get("priority", ""),
                c.get("evidence", ""), c.get("fix", ""),
            ])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("xl/workbook.xml", _WORKBOOK)
        z.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        z.writestr("xl/styles.xml", _STYLES)
        z.writestr("xl/worksheets/sheet1.xml", _sheet_xml(summary_rows))
        z.writestr("xl/worksheets/sheet2.xml", _sheet_xml(check_rows))
    return buf.getvalue()
