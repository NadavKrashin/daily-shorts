"""Price tables used for cost ESTIMATES. Actual billing comes from provider invoices/dashboards and is
reconciled via the expenses table. Verified 2026-10-15 (see docs/technology-selection.md); re-verify
before relying on them - providers change prices often."""
from __future__ import annotations

# USD per 1M tokens (input, output) - Anthropic first-party API list prices.
LLM_PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.00, 50.00),
}
WEB_SEARCH_USD_PER_1K = 10.0  # Anthropic server-side web search tool

# Higgsfield API: pay-as-you-go wallet, priced per output second (video) / per image.
# Their blog quotes e.g. Kling 2.6 at $0.07/s; always prefer the API's cost-estimate endpoint.
HIGGSFIELD_VIDEO_USD_PER_SECOND_DEFAULT = 0.10
HIGGSFIELD_IMAGE_USD_DEFAULT = 0.04

# ElevenLabs bills credits from a subscription; this is the marginal estimate per 1k characters
# (Creator tier ~ $22 / 100k credits; multilingual v2 = 1 credit/char). Fixed plan fee -> expenses.
ELEVENLABS_USD_PER_1K_CHARS = 0.22


def llm_cost(model: str, input_tokens: int, output_tokens: int, searches: int = 0) -> float:
    pin, pout = LLM_PRICES.get(model, LLM_PRICES["claude-opus-5-5"])
    return round(input_tokens / 1e6 * pin + output_tokens / 1e6 * pout + searches / 1000 * WEB_SEARCH_USD_PER_1K, 4)
