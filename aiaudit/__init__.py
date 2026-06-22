"""AI Shopping Readiness Auditor.

Audits product-page URLs for readiness for agentic e-commerce and AI shopping
assistants (ChatGPT / OpenAI, Perplexity, Google Gemini & Shopping, Claude,
Bing/Copilot, Amazon Rufus, Apple, Meta AI).

The package is dependency-light on purpose: it uses ``requests`` when available
(falling back to the standard library) and otherwise relies only on the Python
standard library, so it runs anywhere Python 3.9+ is installed.
"""

APP_NAME = "AI Shopping Readiness Auditor"
VERSION = "1.0.0"
MAX_URLS = 25

# Readiness bands. 85 is the "publish gate" used by agentic-commerce scorers.
BAND_READY = "ready"
BAND_PARTIAL = "partial"
BAND_NOT_READY = "not_ready"

READY_THRESHOLD = 85
PARTIAL_THRESHOLD = 60

BAND_LABELS = {
    BAND_READY: "AI-Ready",
    BAND_PARTIAL: "Partially Ready",
    BAND_NOT_READY: "Not Ready",
}


def band_for_score(score: float) -> str:
    if score >= READY_THRESHOLD:
        return BAND_READY
    if score >= PARTIAL_THRESHOLD:
        return BAND_PARTIAL
    return BAND_NOT_READY
