"""robots.txt fetching and per-bot access evaluation for AI / shopping crawlers.

Implements a Google-compatible matcher: groups are selected by the most
specific matching ``User-agent`` token, and within a group the longest matching
path rule wins (``Allow`` beats ``Disallow`` on equal length). ``*`` and ``$``
wildcards are supported.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .fetcher import fetch, robots_url_for

# The crawlers that matter for agentic commerce and AI shopping surfaces.
# weight = how much its access matters to AI-shopping discoverability.
# category groups them for the report.
AI_BOTS: List[dict] = [
    # OpenAI / ChatGPT
    {"token": "OAI-SearchBot", "label": "OpenAI Search (ChatGPT shopping)", "vendor": "OpenAI", "weight": 3},
    {"token": "ChatGPT-User", "label": "ChatGPT (live browsing)", "vendor": "OpenAI", "weight": 3},
    {"token": "GPTBot", "label": "GPTBot (OpenAI indexing)", "vendor": "OpenAI", "weight": 2},
    # Google
    {"token": "Googlebot", "label": "Googlebot (Search & Shopping)", "vendor": "Google", "weight": 3},
    {"token": "Storebot-Google", "label": "Google Shopping (Storebot)", "vendor": "Google", "weight": 2},
    {"token": "Google-Extended", "label": "Google-Extended (Gemini)", "vendor": "Google", "weight": 2},
    # Perplexity
    {"token": "PerplexityBot", "label": "PerplexityBot", "vendor": "Perplexity", "weight": 2},
    {"token": "Perplexity-User", "label": "Perplexity (live browsing)", "vendor": "Perplexity", "weight": 2},
    # Microsoft / Bing / Copilot
    {"token": "Bingbot", "label": "Bingbot (Bing & Copilot)", "vendor": "Microsoft", "weight": 2},
    # Anthropic / Claude
    {"token": "ClaudeBot", "label": "ClaudeBot (Anthropic indexing)", "vendor": "Anthropic", "weight": 1},
    {"token": "Claude-User", "label": "Claude (live browsing)", "vendor": "Anthropic", "weight": 1},
    {"token": "Claude-SearchBot", "label": "Claude Search", "vendor": "Anthropic", "weight": 1},
    # Others
    {"token": "Amazonbot", "label": "Amazonbot (Alexa / Rufus)", "vendor": "Amazon", "weight": 1},
    {"token": "Applebot-Extended", "label": "Applebot-Extended (Apple AI)", "vendor": "Apple", "weight": 1},
    {"token": "meta-externalagent", "label": "Meta AI", "vendor": "Meta", "weight": 1},
]

TOTAL_BOT_WEIGHT = sum(b["weight"] for b in AI_BOTS)


@dataclass
class BotAccess:
    token: str
    label: str
    vendor: str
    weight: int
    allowed: bool
    matched_agent: str
    matched_rule: Optional[str]


@dataclass
class RobotsResult:
    url: str
    robots_url: str
    status: Optional[int] = None
    fetched: bool = False
    exists: bool = True  # a 404 means "no restrictions"
    error: Optional[str] = None
    bots: List[BotAccess] = field(default_factory=list)
    allowed_weight: int = 0
    total_weight: int = TOTAL_BOT_WEIGHT
    note: str = ""

    @property
    def access_ratio(self) -> float:
        if self.total_weight == 0:
            return 1.0
        return self.allowed_weight / self.total_weight

    @property
    def allowed_count(self) -> int:
        return sum(1 for b in self.bots if b.allowed)

    @property
    def blocked_bots(self) -> List[BotAccess]:
        return [b for b in self.bots if not b.allowed]

    def as_dict(self) -> dict:
        return {
            "robots_url": self.robots_url,
            "status": self.status,
            "fetched": self.fetched,
            "exists": self.exists,
            "error": self.error,
            "note": self.note,
            "access_ratio": round(self.access_ratio, 3),
            "allowed_count": self.allowed_count,
            "bot_count": len(self.bots),
            "bots": [
                {
                    "token": b.token, "label": b.label, "vendor": b.vendor,
                    "allowed": b.allowed, "matched_agent": b.matched_agent,
                    "matched_rule": b.matched_rule,
                }
                for b in self.bots
            ],
        }


# --------------------------------------------------------------------------- #
# Parsing & matching
# --------------------------------------------------------------------------- #

def _parse_groups(text: str) -> List[dict]:
    """Parse robots.txt into a list of ``{"agents": [...], "rules": [...]}``."""
    groups: List[dict] = []
    current: Optional[dict] = None
    started_rules = False

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            if current is not None and started_rules:
                groups.append(current)
                current = None
                started_rules = False
            if current is None:
                current = {"agents": [], "rules": []}
            current["agents"].append(value.lower())
        elif key in ("allow", "disallow"):
            if current is None:
                current = {"agents": ["*"], "rules": []}
            started_rules = True
            current["rules"].append((key, value))
        # sitemap / crawl-delay / host are ignored for access decisions
    if current is not None:
        groups.append(current)
    return groups


def _select_group(groups: List[dict], bot_token: str) -> Optional[dict]:
    """Pick the group with the most specific matching user-agent token."""
    bot = bot_token.lower()
    best: Optional[dict] = None
    best_len = -1
    wildcard: Optional[dict] = None
    for grp in groups:
        for agent in grp["agents"]:
            if agent == "*":
                if wildcard is None:
                    wildcard = grp
                continue
            # Case-insensitive token match (exact or the robots token is a
            # prefix of the bot's product token, e.g. "googlebot").
            if bot == agent or bot.startswith(agent):
                if len(agent) > best_len:
                    best_len = len(agent)
                    best = grp
    return best if best is not None else wildcard


def _rule_to_regex(pattern: str) -> re.Pattern:
    """Translate a robots path pattern (with * and $) into a prefix regex."""
    anchored_end = pattern.endswith("$")
    body = pattern[:-1] if anchored_end else pattern
    out = []
    for ch in body:
        if ch == "*":
            out.append(".*")
        else:
            out.append(re.escape(ch))
    regex = "^" + "".join(out)
    if anchored_end:
        regex += "$"
    return re.compile(regex)


def _path_allowed(rules: List[Tuple[str, str]], path: str) -> Tuple[bool, Optional[str]]:
    """Return (allowed, matched_rule_text) for ``path`` given group rules."""
    best_len = -1
    decision = True  # default allow when nothing matches
    matched_rule: Optional[str] = None
    for kind, value in rules:
        if value == "":
            # Empty Disallow == allow all; empty Allow is meaningless.
            continue
        try:
            rx = _rule_to_regex(value)
        except re.error:
            continue
        if rx.match(path):
            # Length of the raw pattern determines specificity.
            length = len(value)
            if length > best_len or (length == best_len and kind == "allow"):
                best_len = length
                decision = (kind == "allow")
                matched_rule = f"{'Allow' if kind == 'allow' else 'Disallow'}: {value}"
    return decision, matched_rule


def evaluate_robots(text: str, target_url: str) -> Tuple[List[BotAccess], int]:
    """Evaluate every AI bot against parsed robots.txt for ``target_url``."""
    groups = _parse_groups(text)
    parsed = urlparse(target_url)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    results: List[BotAccess] = []
    allowed_weight = 0
    for bot in AI_BOTS:
        grp = _select_group(groups, bot["token"])
        if grp is None:
            allowed, matched_agent, matched_rule = True, "(no matching group)", None
        else:
            allowed, matched_rule = _path_allowed(grp["rules"], path)
            agents = ", ".join(grp["agents"])
            matched_agent = agents
        if allowed:
            allowed_weight += bot["weight"]
        results.append(BotAccess(
            token=bot["token"], label=bot["label"], vendor=bot["vendor"],
            weight=bot["weight"], allowed=allowed,
            matched_agent=matched_agent, matched_rule=matched_rule,
        ))
    return results, allowed_weight


def check_robots(target_url: str, robots_text: Optional[str] = None) -> RobotsResult:
    """Fetch (unless ``robots_text`` supplied) and evaluate robots.txt."""
    robots_url = robots_url_for(target_url)
    result = RobotsResult(url=target_url, robots_url=robots_url)

    if robots_text is None:
        fr = fetch(robots_url, timeout=12, max_retries=1)
        result.status = fr.status
        result.fetched = fr.ok
        if not fr.ok:
            if fr.status == 404:
                result.exists = False
                result.note = "No robots.txt (HTTP 404) — all crawlers allowed by default."
                robots_text = ""
            else:
                # Could not verify; do not tank the score, but flag it.
                result.error = fr.error
                result.note = (
                    "robots.txt could not be retrieved; assuming crawlers are "
                    "allowed. Verify this from an environment with open egress."
                )
                bots, allowed_weight = evaluate_robots("", target_url)
                result.bots = bots
                result.allowed_weight = allowed_weight
                return result
        else:
            robots_text = fr.text
    else:
        result.fetched = True
        result.status = 200

    if not robots_text.strip():
        result.exists = result.exists and (result.status != 404)
        if not result.note:
            result.note = "robots.txt is empty — all crawlers allowed."

    bots, allowed_weight = evaluate_robots(robots_text or "", target_url)
    result.bots = bots
    result.allowed_weight = allowed_weight
    return result
