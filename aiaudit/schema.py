"""Extract and normalise product structured data from raw HTML.

Pulls JSON-LD (``application/ld+json``) plus a few signals from Open Graph /
``product:`` meta tags and microdata, then flattens everything into a single
:class:`ProductProfile` describing which agentic-commerce fields are present.

Only the standard library is used (``html.parser``), so this works without
BeautifulSoup/lxml.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional


# --------------------------------------------------------------------------- #
# HTML parsing
# --------------------------------------------------------------------------- #

class _Extractor(HTMLParser):
    """Collect ld+json script bodies, meta tags, title and microdata hints."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ld_blocks: List[str] = []
        self.metas: List[Dict[str, str]] = []
        self.title_parts: List[str] = []
        self.links: List[Dict[str, str]] = []
        self.itemprops: List[str] = []
        self._in_ld = False
        self._in_title = False
        self._buf: List[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ld = True
            self._buf = []
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "link":
            self.links.append(a)
        if "itemprop" in a:
            self.itemprops.append(a["itemprop"].lower())

    def handle_startendtag(self, tag, attrs):
        # self-closing meta/link
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self.ld_blocks.append("".join(self._buf))
            self._in_ld = False
            self._buf = []
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)
        elif self._in_title:
            self.title_parts.append(data)


def _loads_lenient(text: str) -> Optional[Any]:
    """Parse JSON, tolerating a few common real-world breakages."""
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip JS-style line comments and trailing commas, then retry.
    cleaned = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


# --------------------------------------------------------------------------- #
# JSON-LD flattening
# --------------------------------------------------------------------------- #

def _flatten(node: Any, out: List[dict]) -> None:
    """Collect every dict object reachable in a JSON-LD structure."""
    if isinstance(node, dict):
        out.append(node)
        for v in node.values():
            _flatten(v, out)
    elif isinstance(node, list):
        for item in node:
            _flatten(item, out)


def _types_of(obj: dict) -> List[str]:
    t = obj.get("@type") or obj.get("type")
    if t is None:
        return []
    if isinstance(t, list):
        return [str(x) for x in t]
    return [str(t)]


def _has_type(obj: dict, *names: str) -> bool:
    lowered = {x.lower() for x in _types_of(obj)}
    return any(n.lower() in lowered for n in names)


def _text(value: Any) -> Optional[str]:
    """Best-effort scalar text from a schema value."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("name", "@value", "value", "url", "@id"):
            if key in value:
                return _text(value[key])
    if isinstance(value, list) and value:
        return _text(value[0])
    return None


def _images(value: Any) -> List[str]:
    imgs: List[str] = []

    def add(v: Any) -> None:
        if isinstance(v, str) and v.strip():
            imgs.append(v.strip())
        elif isinstance(v, dict):
            u = v.get("url") or v.get("contentUrl") or v.get("@id")
            if isinstance(u, str) and u.strip():
                imgs.append(u.strip())
        elif isinstance(v, list):
            for item in v:
                add(item)

    add(value)
    return imgs


def _first(objs: List[dict], key: str) -> Any:
    for o in objs:
        if key in o and o[key] not in (None, "", []):
            return o[key]
    return None


def _gtin_value(obj: dict) -> Optional[str]:
    for key in ("gtin13", "gtin12", "gtin14", "gtin8", "gtin", "isbn"):
        v = obj.get(key)
        if v:
            return _text(v)
    return None


# --------------------------------------------------------------------------- #
# Public profile
# --------------------------------------------------------------------------- #

@dataclass
class ProductProfile:
    has_jsonld: bool = False
    jsonld_blocks: int = 0
    jsonld_errors: int = 0
    product_found: bool = False
    is_product_group: bool = False
    types_found: List[str] = field(default_factory=list)
    looks_like_product_page: bool = False  # via OG/meta even if no JSON-LD

    # presence + sample evidence
    fields: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)

    def present(self, name: str) -> bool:
        return bool(self.fields.get(name))

    def as_dict(self) -> dict:
        return {
            "has_jsonld": self.has_jsonld,
            "jsonld_blocks": self.jsonld_blocks,
            "jsonld_errors": self.jsonld_errors,
            "product_found": self.product_found,
            "is_product_group": self.is_product_group,
            "types_found": sorted(set(self.types_found)),
            "looks_like_product_page": self.looks_like_product_page,
            "fields": self.fields,
            "evidence": self.evidence,
            "meta": self.meta,
        }


def _parse_meta(extractor: _Extractor) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    for m in extractor.metas:
        key = (m.get("property") or m.get("name") or "").lower()
        content = m.get("content", "")
        if not key or not content:
            continue
        meta[key] = content
    canonical = None
    for link in extractor.links:
        if (link.get("rel", "").lower() == "canonical") and link.get("href"):
            canonical = link["href"]
            break
    title = "".join(extractor.title_parts).strip()
    return {
        "title": title or None,
        "meta_description": meta.get("description"),
        "canonical": canonical,
        "og_type": meta.get("og:type"),
        "og_title": meta.get("og:title"),
        "og_price_amount": meta.get("product:price:amount") or meta.get("og:price:amount"),
        "og_price_currency": meta.get("product:price:currency") or meta.get("og:price:currency"),
        "og_availability": meta.get("product:availability") or meta.get("og:availability"),
        "og_image": meta.get("og:image"),
        "raw_count": len(meta),
    }


def extract_profile(html: str) -> ProductProfile:
    profile = ProductProfile()
    extractor = _Extractor()
    try:
        extractor.feed(html or "")
    except Exception:
        pass

    profile.meta = _parse_meta(extractor)
    profile.jsonld_blocks = len(extractor.ld_blocks)

    # Parse every JSON-LD block and flatten all objects.
    all_objs: List[dict] = []
    for block in extractor.ld_blocks:
        parsed = _loads_lenient(block)
        if parsed is None:
            profile.jsonld_errors += 1
            continue
        _flatten(parsed, all_objs)

    profile.has_jsonld = profile.jsonld_blocks > 0
    profile.types_found = [t for o in all_objs for t in _types_of(o)]

    product_objs = [o for o in all_objs if _has_type(o, "Product", "ProductGroup")]
    group_objs = [o for o in all_objs if _has_type(o, "ProductGroup")]
    offer_objs = [o for o in all_objs if _has_type(o, "Offer", "AggregateOffer")]
    rating_objs = [o for o in all_objs if _has_type(o, "AggregateRating")]
    review_objs = [o for o in all_objs if _has_type(o, "Review")]
    faq_objs = [o for o in all_objs if _has_type(o, "FAQPage")]
    breadcrumb_objs = [o for o in all_objs if _has_type(o, "BreadcrumbList")]

    profile.product_found = bool(product_objs)
    profile.is_product_group = bool(group_objs)

    # Pick the "main" product: prefer a ProductGroup, else the richest Product.
    main: Optional[dict] = None
    if group_objs:
        main = group_objs[0]
    elif product_objs:
        main = max(product_objs, key=lambda o: len(o.keys()))

    # Offers may live on the product, its variants, or as standalone nodes.
    if main is not None:
        for key in ("offers",):
            v = main.get(key)
            if isinstance(v, dict):
                offer_objs.append(v)
            elif isinstance(v, list):
                offer_objs.extend([x for x in v if isinstance(x, dict)])
        # aggregateRating directly attached
        ar = main.get("aggregateRating")
        if isinstance(ar, dict):
            rating_objs.append(ar)

    def field_from_main(*keys: str) -> Any:
        if main is None:
            return None
        for k in keys:
            if k in main and main[k] not in (None, "", []):
                return main[k]
        return None

    # availability / price / currency from any offer
    price = _first(offer_objs, "price") or _first(offer_objs, "lowPrice") \
        or profile.meta.get("og_price_amount")
    currency = _first(offer_objs, "priceCurrency") or profile.meta.get("og_price_currency")
    availability = _first(offer_objs, "availability") or profile.meta.get("og_availability")
    offer_url = _first(offer_objs, "url")

    # shipping / returns can be nested anywhere in offers
    shipping = any(
        ("shippingDetails" in o) or _has_type(o, "OfferShippingDetails")
        for o in all_objs
    )
    returns = any(
        ("hasMerchantReturnPolicy" in o) or _has_type(o, "MerchantReturnPolicy")
        for o in all_objs
    )

    # variant axis & standardized attributes
    varies_by = field_from_main("variesBy")
    attr_present = []
    for attr in ("color", "size", "material", "pattern"):
        if any(attr in o and o[attr] not in (None, "", []) for o in product_objs):
            attr_present.append(attr)
    has_size_spec = any(_has_type(o, "SizeSpecification") for o in all_objs)
    audience = any("audience" in o and o["audience"] for o in all_objs)
    additional_prop = any("additionalProperty" in o and o["additionalProperty"] for o in all_objs)

    # gtin / sku / mpn — search product objects + variants
    gtin = None
    sku = None
    mpn = None
    brand = None
    for o in product_objs or all_objs:
        gtin = gtin or _gtin_value(o)
        sku = sku or _text(o.get("sku"))
        mpn = mpn or _text(o.get("mpn"))
        if brand is None and o.get("brand"):
            brand = _text(o.get("brand"))
    for o in offer_objs:
        gtin = gtin or _gtin_value(o)
        sku = sku or _text(o.get("sku"))

    # explicit identifier_exists=false (POD / handmade with no GTIN)
    identifier_exists_false = False
    for o in all_objs:
        v = o.get("identifier_exists", o.get("identifierExists"))
        if isinstance(v, str) and v.strip().lower() in ("false", "no"):
            identifier_exists_false = True
        elif v is False:
            identifier_exists_false = True

    # aggregate rating values
    rating_value = _first(rating_objs, "ratingValue")
    review_count = _first(rating_objs, "reviewCount") or _first(rating_objs, "ratingCount")
    review_node_count = len(review_objs)
    if isinstance(field_from_main("review"), list):
        review_node_count = max(review_node_count, len(field_from_main("review")))

    name = field_from_main("name") or profile.meta.get("og_title") or profile.meta.get("title")
    description = field_from_main("description") or profile.meta.get("meta_description")
    images = _images(field_from_main("image"))
    if not images and profile.meta.get("og_image"):
        images = [profile.meta["og_image"]]

    profile.looks_like_product_page = bool(
        product_objs or (profile.meta.get("og_type") == "product")
        or profile.meta.get("og_price_amount")
    )

    desc_text = _text(description)
    profile.fields = {
        "name": _text(name),
        "description": desc_text,
        "description_len": len(desc_text) if desc_text else 0,
        "image": images,
        "image_count": len(images),
        "brand": brand,
        "sku": sku,
        "mpn": mpn,
        "gtin": gtin,
        "identifier_exists_false": identifier_exists_false,
        "price": _text(price),
        "priceCurrency": _text(currency),
        "availability": _text(availability),
        "offer_url": _text(offer_url),
        "aggregateRating": _text(rating_value),
        "review_count": _text(review_count),
        "review_nodes": review_node_count,
        "shipping": shipping,
        "returns": returns,
        "variesBy": varies_by if varies_by else None,
        "variant_attributes": attr_present,
        "size_specification": has_size_spec,
        "audience": audience,
        "additional_property": additional_prop,
        "faq": bool(faq_objs),
        "breadcrumb": bool(breadcrumb_objs),
    }

    profile.evidence = {
        "name": _text(name),
        "price": f"{_text(price)} {_text(currency)}".strip() if price else None,
        "availability": _text(availability),
        "brand": brand,
        "rating": (f"{_text(rating_value)} ({_text(review_count)} reviews)"
                   if rating_value else None),
        "types": sorted(set(profile.types_found))[:8],
        "offers_found": len(offer_objs),
    }
    return profile
