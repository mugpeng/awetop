"""Pricing: LiteLLM cache + custom overrides + cost calculation."""

import json
import os
import time
from typing import Optional

from .snapshot import Tokens

PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/"
    "main/model_prices_and_context_window.json"
)
CACHE_TTL_SECS = 3600  # 1 hour


def _config_dir() -> str:
    d = os.path.expanduser("~/.config/awetop")
    os.makedirs(d, exist_ok=True)
    return d


def _cache_path() -> str:
    return os.path.join(_config_dir(), "pricing-cache.json")


def _custom_path() -> str:
    return os.path.join(_config_dir(), "custom-pricing.json")


def _fetch_litellm() -> Optional[dict]:
    """Fetch LiteLLM pricing JSON from GitHub. Returns None on failure."""
    try:
        import urllib.request

        req = urllib.request.Request(PRICING_URL, headers={"User-Agent": "awetop"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _load_cached_pricing() -> Optional[dict]:
    """Load pricing from cache if fresh enough."""
    path = _cache_path()
    if not os.path.exists(path):
        return None
    try:
        mtime = os.path.getmtime(path)
        if time.time() - mtime > CACHE_TTL_SECS:
            return None
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _save_cache(data: dict) -> None:
    try:
        with open(_cache_path(), "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def load_litellm_pricing() -> dict:
    """Load LiteLLM pricing, using cache or fetching fresh."""
    cached = _load_cached_pricing()
    if cached is not None:
        return cached
    fresh = _fetch_litellm()
    if fresh is not None:
        _save_cache(fresh)
        return fresh
    # Try stale cache as fallback
    path = _cache_path()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def load_custom_pricing() -> dict:
    """Load custom pricing overrides."""
    path = _custom_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _get_model_price(model: str, litellm: dict, custom: dict) -> Optional[dict]:
    """Get pricing for a model. Returns dict with input/output/cache_read/cache_create per-M prices."""
    # 1. Custom overrides (exact match)
    if model in custom:
        return _normalize_price(custom[model])

    # 2. LiteLLM (try multiple key formats)
    for key in [model, f"claude/{model}", f"anthropic/{model}"]:
        if key in litellm:
            entry = litellm[key]
            if isinstance(entry, dict) and "input_cost_per_token" in entry:
                return _normalize_price(entry)

    # 3. Partial match in LiteLLM
    low = model.lower()
    for key, entry in litellm.items():
        if not isinstance(entry, dict):
            continue
        if "input_cost_per_token" not in entry:
            continue
        if low in key.lower() or key.lower() in low:
            return _normalize_price(entry)

    return None


def _normalize_price(entry: dict) -> dict:
    """Normalize price entry to per-million-token format."""
    # LiteLLM uses per-token rates
    if "input_cost_per_token" in entry:
        return {
            "input": entry.get("input_cost_per_token", 0) * 1_000_000,
            "output": entry.get("output_cost_per_token", 0) * 1_000_000,
            "cache_read": entry.get("cache_read_input_token_cost", 0) * 1_000_000,
            "cache_create": entry.get("cache_creation_input_token_cost", 0)
            * 1_000_000,
        }
    # Custom format: per-million-token directly
    return {
        "input": entry.get("input", 0),
        "output": entry.get("output", 0),
        "cache_read": entry.get("cache_read", entry.get("input", 0) * 0.1),
        "cache_create": entry.get("cache_create", entry.get("input", 0)),
    }


def compute_cost(
    tokens: Tokens, model: str, litellm: dict, custom: dict
) -> Optional[float]:
    """Compute cost in USD for a session's token usage."""
    if not model:
        return None
    price = _get_model_price(model, litellm, custom)
    if price is None:
        return None

    cost = (
        tokens.input * price["input"]
        + tokens.output * price["output"]
        + tokens.cache_read * price["cache_read"]
        + tokens.cache_create * price["cache_create"]
    ) / 1_000_000

    return round(cost, 4)
