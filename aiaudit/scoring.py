"""Readiness scoring rubric and per-check evaluation.

The model awards 100 points across seven categories. Each check yields a
status (pass / partial / fail / na), points earned, evidence and — when it is
not a full pass — a concrete, prioritised fix recommendation.

    A  AI Agent Accessibility .............. 12
    B  robots.txt AI Crawler Access ........ 15
    C  Structured Data Foundation .......... 13
    D  Core Product Fields ................. 30
    E  Trust Signals (reviews & ratings) ... 12
    F  Commerce Details (shipping/returns) . 8
    G  Agent Clarity & Enrichment .......... 10
                                           ----
                                            100
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import band_for_score, BAND_LABELS

CATEGORIES = [
    {"id": "A", "label": "AI Agent Accessibility", "max": 12},
    {"id": "B", "label": "robots.txt AI Crawler Access", "max": 15},
    {"id": "C", "label": "Structured Data Foundation", "max": 13},
    {"id": "D", "label": "Core Product Fields", "max": 30},
    {"id": "E", "label": "Trust Signals (Reviews & Ratings)", "max": 12},
    {"id": "F", "label": "Commerce Details (Shipping & Returns)", "max": 8},
    {"id": "G", "label": "Agent Clarity & Enrichment", "max": 10},
]
CATEGORY_LABEL = {c["id"]: c["label"] for c in CATEGORIES}

STATUS_PASS = "pass"
STATUS_PARTIAL = "partial"
STATUS_FAIL = "fail"
STATUS_NA = "na"


@dataclass
class Check:
    id: str
    label: str
    category: str
    possible: float
    earned: float
    status: str
    evidence: str = ""
    fix: str = ""
    impact: str = ""

    @property
    def lost(self) -> float:
        return max(0.0, self.possible - self.earned)

    @property
    def priority(self) -> str:
        if self.status == STATUS_PASS or self.lost <= 0:
            return "none"
        if self.lost >= 7:
            return "high"
        if self.lost >= 4:
            return "medium"
        return "low"

    def as_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "category": self.category,
            "category_label": CATEGORY_LABEL.get(self.category, self.category),
            "possible": round(self.possible, 1), "earned": round(self.earned, 1),
            "status": self.status, "evidence": self.evidence,
            "fix": self.fix, "impact": self.impact, "priority": self.priority,
            "lost": round(self.lost, 1),
        }


def _na(check_id, label, cat, possible, reason) -> Check:
    return Check(check_id, label, cat, possible, 0.0, STATUS_NA,
                 evidence=reason, fix="", impact="")


def evaluate(profile, robots_result, fetch_result) -> List[Check]:
    """Return the full list of checks for one audited page."""
    checks: List[Check] = []
    f = profile.fields if profile else {}
    reachable = bool(fetch_result and fetch_result.ok)

    # ---------------------------------------------------------------- A: access
    if reachable:
        checks.append(Check(
            "A1", "Page reachable by AI agents (HTTP 200)", "A", 6, 6, STATUS_PASS,
            evidence=f"HTTP {fetch_result.status} in {fetch_result.elapsed_ms} ms.",
            impact="Agents must be able to load the page at all.",
        ))
    else:
        err = fetch_result.error if fetch_result else "Not fetched."
        checks.append(Check(
            "A1", "Page reachable by AI agents (HTTP 200)", "A", 6, 0, STATUS_FAIL,
            evidence=err or "Page could not be retrieved.",
            fix="Make the product URL return HTTP 200 to non-browser clients. "
                "Avoid blocking by IP/UA, bot-walls or aggressive rate limits, "
                "and ensure it is not behind login.",
            impact="If the page can't be fetched, no AI agent can read or recommend it.",
        ))

    if reachable:
        if profile.product_found:
            checks.append(Check(
                "A2", "Product content server-rendered (not JS-only)", "A", 4, 4,
                STATUS_PASS,
                evidence="Product structured data is present in the server HTML.",
                impact="Most AI crawlers do not execute JavaScript.",
            ))
        elif profile.looks_like_product_page:
            checks.append(Check(
                "A2", "Product content server-rendered (not JS-only)", "A", 4, 1,
                STATUS_PARTIAL,
                evidence="Looks like a product page (OG/meta) but no server-rendered "
                         "Product JSON-LD was found — content may be JS-injected.",
                fix="Server-render the product details and JSON-LD so non-JS crawlers "
                    "(GPTBot, Googlebot, PerplexityBot) can read them.",
                impact="JS-only content is invisible to most AI shopping crawlers.",
            ))
        else:
            checks.append(Check(
                "A2", "Product content server-rendered (not JS-only)", "A", 4, 0,
                STATUS_FAIL,
                evidence="No server-rendered product content detected.",
                fix="Ensure product details render in the initial HTML response.",
                impact="JS-only content is invisible to most AI shopping crawlers.",
            ))

        soft_404 = len(fetch_result.text or "") < 500
        if soft_404:
            checks.append(Check(
                "A3", "Page returns real content (not empty / soft-404)", "A", 2, 0,
                STATUS_FAIL,
                evidence=f"Only {len(fetch_result.text or '')} bytes returned.",
                fix="Verify the URL serves a full product page, not an error or "
                    "placeholder shell.",
            ))
        else:
            checks.append(Check(
                "A3", "Page returns real content (not empty / soft-404)", "A", 2, 2,
                STATUS_PASS,
                evidence=f"{len(fetch_result.text or '')} bytes of HTML returned.",
            ))
    else:
        checks.append(_na("A2", "Product content server-rendered (not JS-only)", "A", 4,
                          "Not assessed — page not reachable."))
        checks.append(_na("A3", "Page returns real content (not empty / soft-404)", "A", 2,
                          "Not assessed — page not reachable."))

    # ---------------------------------------------------------------- B: robots
    checks.append(_robots_check(robots_result))

    # ------------------------------------------------------- C: structured data
    if not reachable:
        checks.append(_na("C1", "Valid JSON-LD structured data present", "C", 5,
                          "Not assessed — page not reachable."))
        checks.append(_na("C2", "Product / ProductGroup schema type present", "C", 8,
                          "Not assessed — page not reachable."))
    else:
        if profile.has_jsonld and profile.jsonld_blocks > profile.jsonld_errors:
            ev = f"{profile.jsonld_blocks} JSON-LD block(s) found"
            if profile.jsonld_errors:
                ev += f" ({profile.jsonld_errors} failed to parse)"
            earned = 5 if profile.jsonld_errors == 0 else 3
            checks.append(Check(
                "C1", "Valid JSON-LD structured data present", "C", 5, earned,
                STATUS_PASS if profile.jsonld_errors == 0 else STATUS_PARTIAL,
                evidence=ev + ".",
                fix=("" if profile.jsonld_errors == 0 else
                     "Fix the malformed JSON-LD block(s) so all parse cleanly."),
                impact="Structured data is how agents read product facts unambiguously.",
            ))
        else:
            checks.append(Check(
                "C1", "Valid JSON-LD structured data present", "C", 5, 0, STATUS_FAIL,
                evidence="No parseable JSON-LD found in the page HTML.",
                fix="Add server-rendered JSON-LD (schema.org/Product) to the page. "
                    "On Shopify this lives in the product template / theme.liquid.",
                impact="Without schema, agents must guess from raw text and usually skip the product.",
            ))

        if profile.product_found:
            t = "ProductGroup" if profile.is_product_group else "Product"
            checks.append(Check(
                "C2", "Product / ProductGroup schema type present", "C", 8, 8, STATUS_PASS,
                evidence=f"schema.org/{t} detected.",
                impact="The Product type is the anchor every shopping agent looks for.",
            ))
        else:
            checks.append(Check(
                "C2", "Product / ProductGroup schema type present", "C", 8, 0, STATUS_FAIL,
                evidence="No schema.org/Product (or ProductGroup) type found.",
                fix="Mark up the page as schema.org/Product (use ProductGroup with "
                    "hasVariant for variant products).",
                impact="No Product type = the page is not recognised as a buyable item.",
            ))

    # --------------------------------------------------------- D: core fields
    if not reachable:
        for cid, lbl, pts in _D_SPECS:
            checks.append(_na(cid, lbl, "D", pts, "Not assessed — page not reachable."))
    else:
        checks.extend(_core_field_checks(f))

    # -------------------------------------------------------- E: trust signals
    if not reachable:
        checks.append(_na("E1", "Aggregate rating present", "E", 7,
                          "Not assessed — page not reachable."))
        checks.append(_na("E2", "Customer reviews present", "E", 5,
                          "Not assessed — page not reachable."))
    else:
        if f.get("aggregateRating"):
            checks.append(Check(
                "E1", "Aggregate rating present", "E", 7, 7, STATUS_PASS,
                evidence=f"aggregateRating = {f.get('aggregateRating')} "
                         f"({f.get('review_count') or '?'} reviews).",
                impact="Ratings are the single biggest trust lever across every agent.",
            ))
        else:
            checks.append(Check(
                "E1", "Aggregate rating present", "E", 7, 0, STATUS_FAIL,
                evidence="No aggregateRating in structured data.",
                fix="Install a reviews app (Judge.me / Loox / Shopify Product Reviews) "
                    "that injects aggregateRating + review into the server-rendered "
                    "Product JSON-LD. Even 5–10 real reviews flips this from 0 → full.",
                impact="Agents heavily weight social proof when choosing what to recommend.",
            ))
        if (f.get("review_nodes") or 0) > 0:
            checks.append(Check(
                "E2", "Customer reviews present", "E", 5, 5, STATUS_PASS,
                evidence=f"{f.get('review_nodes')} review node(s) in schema.",
            ))
        else:
            checks.append(Check(
                "E2", "Customer reviews present", "E", 5, 0, STATUS_FAIL,
                evidence="No individual Review nodes in structured data.",
                fix="Expose individual reviews as schema.org/Review nodes alongside "
                    "the aggregate rating.",
                impact="Review text gives agents specifics to quote when recommending.",
            ))

    # ------------------------------------------------------ F: commerce details
    if not reachable:
        checks.append(_na("F1", "Shipping details in schema", "F", 4,
                          "Not assessed — page not reachable."))
        checks.append(_na("F2", "Return policy in schema", "F", 4,
                          "Not assessed — page not reachable."))
    else:
        checks.append(_bool_check(
            "F1", "Shipping details in schema", "F", 4, bool(f.get("shipping")),
            ok_ev="OfferShippingDetails present.",
            bad_ev="No shippingDetails in the offer.",
            fix="Add OfferShippingDetails (rates, handling time, delivery time) to the "
                "offer so agents can quote delivery.",
            impact="Agents increasingly filter and rank on delivery speed and cost.",
        ))
        checks.append(_bool_check(
            "F2", "Return policy in schema", "F", 4, bool(f.get("returns")),
            ok_ev="hasMerchantReturnPolicy present.",
            bad_ev="No hasMerchantReturnPolicy in the offer.",
            fix="Add hasMerchantReturnPolicy (window, fees, method) so agents can "
                "surface return terms.",
            impact="Return terms are a common buyer question agents try to answer.",
        ))

    # ----------------------------------------------------- G: clarity/enrichment
    if not reachable:
        for cid, lbl, pts in _G_SPECS:
            checks.append(_na(cid, lbl, "G", pts, "Not assessed — page not reachable."))
    else:
        checks.extend(_clarity_checks(f))

    return checks


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

_D_SPECS = [
    ("D1", "Product name", 3), ("D2", "Product description", 3),
    ("D3", "Product image", 3), ("D4", "Price", 4),
    ("D5", "Price currency", 3), ("D6", "Availability / stock status", 4),
    ("D7", "Brand", 3), ("D8", "SKU / MPN identifier", 3),
    ("D9", "GTIN / barcode", 4),
]

_G_SPECS = [
    ("G1", "Description is rich enough for agents", 3),
    ("G2", "Multiple product images (≥3)", 2),
    ("G3", "Variant axis & attributes exposed", 2),
    ("G4", "Audience / FAQ / extra attributes", 2),
    ("G5", "Findability (canonical / breadcrumb / offer URL)", 1),
]


def _bool_check(cid, label, cat, pts, ok, ok_ev, bad_ev, fix, impact="") -> Check:
    if ok:
        return Check(cid, label, cat, pts, pts, STATUS_PASS, evidence=ok_ev, impact=impact)
    return Check(cid, label, cat, pts, 0, STATUS_FAIL, evidence=bad_ev, fix=fix, impact=impact)


def _robots_check(robots_result) -> Check:
    if robots_result is None:
        return _na("B1", "robots.txt allows AI & shopping crawlers", "B", 15,
                   "robots.txt not evaluated.")
    ratio = robots_result.access_ratio
    earned = round(ratio * 15, 1)
    allowed = robots_result.allowed_count
    total = len(robots_result.bots)
    blocked = robots_result.blocked_bots
    if robots_result.error and not robots_result.fetched:
        return Check(
            "B1", "robots.txt allows AI & shopping crawlers", "B", 15, 15, STATUS_PASS,
            evidence=robots_result.note or "robots.txt unverifiable; assumed open.",
            impact="robots.txt is the gate that lets AI shopping crawlers in.",
        )
    if not blocked:
        note = robots_result.note or f"All {total} AI/shopping crawlers allowed."
        return Check(
            "B1", "robots.txt allows AI & shopping crawlers", "B", 15, 15, STATUS_PASS,
            evidence=note, impact="robots.txt is the gate that lets AI shopping crawlers in.",
        )
    names = ", ".join(b.token for b in blocked)
    status = STATUS_PARTIAL if ratio >= 0.5 else STATUS_FAIL
    return Check(
        "B1", "robots.txt allows AI & shopping crawlers", "B", 15, earned, status,
        evidence=f"{allowed}/{total} crawlers allowed. Blocked: {names}.",
        fix=f"Update robots.txt to allow these crawlers for product URLs: {names}. "
            "Remove blanket Disallow rules that catch AI user-agents, or add explicit "
            "Allow rules for them.",
        impact="Blocked crawlers cannot index the product for their AI shopping surface.",
    )


def _core_field_checks(f: Dict[str, Any]) -> List[Check]:
    out: List[Check] = []
    out.append(_bool_check(
        "D1", "Product name", "D", 3, bool(f.get("name")),
        ok_ev=f"name = \"{_short(f.get('name'))}\".",
        bad_ev="No product name in schema.",
        fix="Add a clear, specific product name to the Product schema.",
        impact="The name is how an agent identifies and cites the product.",
    ))
    out.append(_bool_check(
        "D2", "Product description", "D", 3, bool(f.get("description")),
        ok_ev=f"description present ({f.get('description_len')} chars).",
        bad_ev="No description in schema.",
        fix="Add a descriptive, benefit-led product description to the schema.",
        impact="Agents summarise and match products from the description.",
    ))
    out.append(_bool_check(
        "D3", "Product image", "D", 3, bool(f.get("image")),
        ok_ev=f"{f.get('image_count')} image(s) in schema.",
        bad_ev="No image in schema.",
        fix="Add at least one high-resolution image URL to the Product schema.",
        impact="Agents and AI shopping UIs render the product image.",
    ))
    out.append(_bool_check(
        "D4", "Price", "D", 4, bool(f.get("price")),
        ok_ev=f"price = {f.get('price')}.",
        bad_ev="No machine-readable price in the offer.",
        fix="Expose offers.price as a number in the Product/Offer schema.",
        impact="No price = the item can't enter price-aware agent comparisons.",
    ))
    out.append(_bool_check(
        "D5", "Price currency", "D", 3, bool(f.get("priceCurrency")),
        ok_ev=f"priceCurrency = {f.get('priceCurrency')}.",
        bad_ev="No priceCurrency in the offer.",
        fix="Add offers.priceCurrency (ISO 4217, e.g. USD) to the offer.",
        impact="Currency is required for agents to compare and transact.",
    ))
    out.append(_bool_check(
        "D6", "Availability / stock status", "D", 4, bool(f.get("availability")),
        ok_ev=f"availability = {_short(f.get('availability'))}.",
        bad_ev="No availability in the offer.",
        fix="Add offers.availability (e.g. https://schema.org/InStock).",
        impact="Agents avoid recommending items they can't confirm are in stock.",
    ))
    out.append(_bool_check(
        "D7", "Brand", "D", 3, bool(f.get("brand")),
        ok_ev=f"brand = {_short(f.get('brand'))}.",
        bad_ev="No brand in schema.",
        fix="Add the brand (schema.org/Brand) to the Product schema.",
        impact="Brand drives matching for branded shopping queries.",
    ))
    out.append(_bool_check(
        "D8", "SKU / MPN identifier", "D", 3, bool(f.get("sku") or f.get("mpn")),
        ok_ev=f"sku/mpn = {_short(f.get('sku') or f.get('mpn'))}.",
        bad_ev="No SKU or MPN in schema.",
        fix="Add sku and/or mpn so agents can uniquely reference the item.",
        impact="Stable identifiers let agents track and re-find the exact product.",
    ))
    # GTIN with POD nuance
    if f.get("gtin"):
        out.append(Check(
            "D9", "GTIN / barcode", "D", 4, 4, STATUS_PASS,
            evidence=f"gtin = {f.get('gtin')}.",
            impact="GTIN is the strongest product-match key for Google & ChatGPT feeds.",
        ))
    elif f.get("identifier_exists_false"):
        out.append(Check(
            "D9", "GTIN / barcode", "D", 4, 2.5, STATUS_PARTIAL,
            evidence="No GTIN, but identifier_exists=false is declared (acceptable for "
                     "POD / handmade items).",
            fix="For premium lines consider buying a GS1 prefix and assigning GTIN-13; "
                "otherwise keep identifier_exists=false in the Google feed.",
            impact="Missing GTIN is tolerated when explicitly declared, but a real GTIN "
                   "maximises match confidence.",
        ))
    else:
        out.append(Check(
            "D9", "GTIN / barcode", "D", 4, 0, STATUS_FAIL,
            evidence="No GTIN/barcode in schema.",
            fix="Add gtin (gtin13/12/8) where you have one. For POD/handmade with no "
                "GTIN, set identifier_exists=false in the Google feed so you are not "
                "penalised for the gap.",
            impact="GTIN is the strongest product-match key for Google & ChatGPT feeds.",
        ))
    return out


def _clarity_checks(f: Dict[str, Any]) -> List[Check]:
    out: List[Check] = []
    desc_len = f.get("description_len") or 0
    if desc_len >= 150:
        out.append(Check("G1", "Description is rich enough for agents", "G", 3, 3,
                         STATUS_PASS, evidence=f"Description is {desc_len} chars."))
    elif desc_len > 0:
        out.append(Check("G1", "Description is rich enough for agents", "G", 3, 1,
                         STATUS_PARTIAL,
                         evidence=f"Description is short ({desc_len} chars).",
                         fix="Expand the description to ~150+ chars covering materials, "
                             "use, sizing and benefits so agents can match more queries.",
                         impact="Thin descriptions match fewer shopping intents."))
    else:
        out.append(Check("G1", "Description is rich enough for agents", "G", 3, 0,
                         STATUS_FAIL, evidence="No description text available.",
                         fix="Add a detailed product description."))

    img = f.get("image_count") or 0
    if img >= 3:
        out.append(Check("G2", "Multiple product images (≥3)", "G", 2, 2, STATUS_PASS,
                         evidence=f"{img} images."))
    elif img >= 1:
        out.append(Check("G2", "Multiple product images (≥3)", "G", 2, 1, STATUS_PARTIAL,
                         evidence=f"Only {img} image(s).",
                         fix="Provide at least 3 images (angles, scale, in-use)."))
    else:
        out.append(Check("G2", "Multiple product images (≥3)", "G", 2, 0, STATUS_FAIL,
                         evidence="No images.", fix="Add multiple product images."))

    has_variant_axis = bool(f.get("variesBy")) or bool(f.get("variant_attributes")) \
        or bool(f.get("size_specification"))
    if has_variant_axis:
        bits = []
        if f.get("variesBy"):
            bits.append("variesBy")
        if f.get("variant_attributes"):
            bits.append("/".join(f.get("variant_attributes")))
        if f.get("size_specification"):
            bits.append("SizeSpecification")
        out.append(Check("G3", "Variant axis & attributes exposed", "G", 2, 2, STATUS_PASS,
                         evidence="Exposed: " + ", ".join(bits) + "."))
    else:
        out.append(Check("G3", "Variant axis & attributes exposed", "G", 2, 0, STATUS_FAIL,
                         evidence="No variesBy / color / size / material / pattern in schema.",
                         fix="Expose standardized attributes (color, size, material, "
                             "pattern) and, for variant products, variesBy on the "
                             "ProductGroup so agents can filter.",
                         impact="Agents can't filter on attributes that live only in tags/titles."))

    enrich = sum(bool(f.get(k)) for k in ("audience", "additional_property", "faq"))
    if enrich >= 2:
        out.append(Check("G4", "Audience / FAQ / extra attributes", "G", 2, 2, STATUS_PASS,
                         evidence="Enrichment present (audience / FAQ / additionalProperty)."))
    elif enrich == 1:
        out.append(Check("G4", "Audience / FAQ / extra attributes", "G", 2, 1, STATUS_PARTIAL,
                         evidence="Some enrichment present.",
                         fix="Add the remaining enrichment: audience (PeopleAudience), "
                             "FAQPage, and additionalProperty where relevant."))
    else:
        out.append(Check("G4", "Audience / FAQ / extra attributes", "G", 2, 0, STATUS_FAIL,
                         evidence="No audience, FAQ or additionalProperty enrichment.",
                         fix="Add audience (PeopleAudience: suggestedGender/Age), an "
                             "FAQPage, and additionalProperty to enrich agent context."))

    find = sum(bool(f.get(k)) for k in ("offer_url",)) + \
        (1 if f.get("breadcrumb") else 0)
    if find >= 1:
        out.append(Check("G5", "Findability (canonical / breadcrumb / offer URL)", "G", 1, 1,
                         STATUS_PASS, evidence="Offer URL / breadcrumb present."))
    else:
        out.append(Check("G5", "Findability (canonical / breadcrumb / offer URL)", "G", 1, 0,
                         STATUS_FAIL, evidence="No offer URL or breadcrumb.",
                         fix="Add offers.url and BreadcrumbList so agents can link to and "
                             "place the product."))
    return out


def _short(value: Any, n: int = 60) -> str:
    s = "" if value is None else str(value)
    return (s[: n - 1] + "…") if len(s) > n else s


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #

def summarize(checks: List[Check]) -> dict:
    """Roll checks up into category totals, a 0-100 score and a readiness band."""
    cat_totals: Dict[str, Dict[str, float]] = {
        c["id"]: {"earned": 0.0, "possible": 0.0} for c in CATEGORIES
    }
    total_earned = 0.0
    total_possible = 0.0
    for ch in checks:
        cat_totals[ch.category]["earned"] += ch.earned
        cat_totals[ch.category]["possible"] += ch.possible
        total_earned += ch.earned
        total_possible += ch.possible

    score = round((total_earned / total_possible) * 100) if total_possible else 0
    band = band_for_score(score)

    categories = []
    for c in CATEGORIES:
        t = cat_totals[c["id"]]
        pct = round((t["earned"] / t["possible"]) * 100) if t["possible"] else 0
        categories.append({
            "id": c["id"], "label": c["label"],
            "earned": round(t["earned"], 1), "possible": round(t["possible"], 1),
            "pct": pct,
        })

    # Prioritised fix list: anything not a full pass, worst-loss first.
    fixes = []
    for ch in sorted(checks, key=lambda c: (-c.lost, c.id)):
        if ch.status in (STATUS_FAIL, STATUS_PARTIAL) and ch.fix:
            fixes.append({
                "priority": ch.priority,
                "title": ch.label,
                "detail": ch.fix,
                "category": CATEGORY_LABEL.get(ch.category, ch.category),
                "points": round(ch.lost, 1),
                "check_id": ch.id,
            })

    return {
        "score": score,
        "band": band,
        "band_label": BAND_LABELS[band],
        "categories": categories,
        "fixes": fixes,
        "earned": round(total_earned, 1),
        "possible": round(total_possible, 1),
    }
