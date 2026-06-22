# AI Shopping Readiness Auditor

Audit product‑page URLs and find out whether they're ready for **agentic
e‑commerce and AI shopping assistants** — ChatGPT/OpenAI, Perplexity, Google
Gemini & Shopping, Claude, Bing/Copilot, Amazon (Rufus), Apple and Meta AI.

Paste **one URL or up to 25 at once**, and the tool scans each page and produces
a clear audit: AI‑agent accessibility, robots.txt access for AI/shopping
crawlers, structured‑data/schema validity and completeness, a **0–100 readiness
score**, a **prioritised list of fixes**, a **summary dashboard**, and **CSV /
Excel export**.

Inspired by Shopify's free product‑page audit concept for agentic commerce.
Reference: <https://www.shopify.com/blog/how-agentic-commerce-works>

---

## Why this exists

AI shopping agents don't browse like people. They fetch the raw HTML (usually
without running JavaScript), read **structured data** (schema.org JSON‑LD), and
will only consider a product if its **robots.txt lets their crawler in** and the
**product facts are present and machine‑readable**. This tool checks exactly
those things and tells you what to fix first.

## Features (what you asked for → where it is)

| Requirement | Delivered |
|---|---|
| Enter **one URL** or **up to 25** (paste or upload) | Web UI textarea + `.txt`/`.csv` upload; CLI args or `--file` |
| Page **accessible to AI agents** | Category **A** — reachability + server‑rendered (non‑JS) content |
| **robots.txt** allows AI crawlers & shopping bots | Category **B** — per‑bot matrix for 15 AI/shopping crawlers |
| **Valid structured data / schema** | Category **C** — JSON‑LD parses + Product/ProductGroup type |
| **Key product fields** (name, description, image, price, currency, availability, brand, SKU/GTIN, reviews, ratings, shipping/returns) | Categories **D / E / F** |
| **Clear enough for AI agents to recommend** | Category **G** — description richness, images, variant attributes, audience/FAQ, findability |
| **Missing / weak fields** | Every failing/partial check lists the gap + evidence |
| **Readiness score** per URL | 0–100, banded **AI‑Ready / Partially Ready / Not Ready** |
| **Prioritised fixes** per page | High/Medium/Low, ranked by score impact |
| **Summary dashboard** | Ready / partial / not‑ready counts + averages + table |
| **Export CSV or Excel** | One‑click CSV (summary or all‑checks) and real `.xlsx` |

## Quick start

No third‑party install is required (the tool runs on the Python 3.9+ standard
library; it uses [`requests`](https://pypi.org/project/requests/) automatically
if present).

### Web UI

```bash
python run.py            # then open http://127.0.0.1:8000
python run.py --open     # also opens your browser
python run.py --host 0.0.0.0 --port 8080
```

Paste URLs (one per line) or upload a `.txt`/`.csv`, click **Run Audit**, then
explore the dashboard, per‑page reports, and export buttons.

### Command line

```bash
python cli.py https://store.com/products/a https://store.com/products/b
python cli.py --file urls.txt
python cli.py --file urls.txt --csv summary.csv --xlsx report.xlsx --json report.json
```

```
  SCORE  STATUS     ROBOTS  URL
  ------------------------------------------------------------------------------
    100  READY        100%  https://store.com/products/a
     81  PARTIAL      100%  https://store.com/products/b
     35  NOT READY     92%  https://store.com/products/c
  ------------------------------------------------------------------------------
  3 pages · avg 72 · 1 ready / 1 partial / 1 not ready
```

## Scoring rubric (100 points)

| | Category | Points | Checks |
|---|---|---:|---|
| **A** | AI Agent Accessibility | 12 | Reachable (HTTP 200), server‑rendered (non‑JS) product content, real content (not soft‑404) |
| **B** | robots.txt AI Crawler Access | 15 | Weighted access for 15 AI/shopping crawlers for the product URL |
| **C** | Structured Data Foundation | 13 | JSON‑LD present & parses, `Product`/`ProductGroup` type |
| **D** | Core Product Fields | 30 | name, description, image, price, currency, availability, brand, SKU/MPN, GTIN |
| **E** | Trust Signals | 12 | `aggregateRating`, individual `review`s |
| **F** | Commerce Details | 8 | shipping details, return policy |
| **G** | Agent Clarity & Enrichment | 10 | description richness, ≥3 images, variant attributes/`variesBy`, audience/FAQ/`additionalProperty`, findability |

**Bands:** **AI‑Ready ≥ 85** · **Partially Ready 60–84** · **Not Ready < 60**
(85 mirrors the common agentic‑commerce "publish gate").

### GTIN nuance (print‑on‑demand / handmade)

Missing GTIN normally fails the GTIN check, but if the page/feed explicitly
declares `identifier_exists=false` (the correct signal for POD/handmade items
with no retail barcode), it is scored as a **partial pass** instead of a fail —
so you're not penalised for a barcode that legitimately doesn't exist.

## AI & shopping crawlers checked in robots.txt

OpenAI `OAI-SearchBot`, `ChatGPT-User`, `GPTBot` · Google `Googlebot`,
`Storebot-Google`, `Google-Extended` · `PerplexityBot`, `Perplexity-User` ·
Microsoft `Bingbot` · Anthropic `ClaudeBot`, `Claude-User`, `Claude-SearchBot` ·
`Amazonbot` · `Applebot-Extended` · Meta `meta-externalagent`.

The robots matcher is Google‑compatible: it picks the most specific
`User-agent` group and applies the longest‑matching path rule (`Allow` beats
`Disallow` on equal length), with `*` and `$` wildcard support.

## Exports

* **CSV (summary)** — one row per URL with score, band, robots %, every key
  field's status and the top 3 fixes.
* **CSV (all checks)** — one row per individual check across all URLs.
* **Excel `.xlsx`** — a real workbook (`Summary` + `Checks` sheets), written
  with the standard library (no `openpyxl` needed).

## Project layout

```
aiaudit/
  fetcher.py    HTTP fetch (requests→urllib fallback), browser UA, retries, file://
  robots.py     robots.txt parsing + AI/shopping crawler access matrix
  schema.py     HTML → JSON-LD / OG / microdata extraction & product profile
  scoring.py    100-point rubric, per-check evaluation, prioritised fixes
  engine.py     per-URL orchestration + concurrent batch runner (≤25)
  exporter.py   CSV + standard-library .xlsx writer
  server.py     dependency-free web UI + JSON API (http.server)
web/            single-page UI (index.html, styles.css, app.js)
run.py          launch the web UI
cli.py          batch auditor for the terminal / CI
tests/          offline tests + HTML fixtures (no network needed)
```

## Tests

```bash
python tests/test_engine.py     # or: pytest -q
```

Tests run fully offline against bundled HTML fixtures (ready / partial /
not‑ready product pages) and cover the robots matcher, scoring bands and both
exporters.

## Network notes

The auditor fetches each product page and its `robots.txt` over HTTPS, so it
needs outbound network access. In a sandbox with an **egress allowlist** (e.g.
Claude Code on the web), blocked hosts return `host_not_allowed`; the tool
reports this clearly per URL instead of failing, and the audit still runs once
you run it locally or add the host to your egress settings. See
<https://code.claude.com/docs/en/claude-code-on-the-web>.
