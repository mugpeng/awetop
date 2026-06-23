"""Read aweswitch config to match profiles and categories."""

import json
import os
from typing import Optional


def load_aweswitch_profiles() -> dict:
    """Load aweswitch config.json. Returns empty dict if not found."""
    path = os.path.expanduser("~/.config/aweswitch/config.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def match_profile(model: str, config: dict) -> str:
    """Match a model name to an aweswitch profile name."""
    if not config or not model:
        return "-"

    profiles = config.get("profiles", {})
    low_model = model.lower()

    for provider, provider_profiles in profiles.items():
        if not isinstance(provider_profiles, dict):
            continue
        for name, profile_data in provider_profiles.items():
            if not isinstance(profile_data, dict):
                continue
            profile_model = profile_data.get("ANTHROPIC_MODEL", "")
            if profile_model and profile_model.lower() == low_model:
                return name
            # Also check OPENAI_MODEL for codex profiles
            profile_model = profile_data.get("OPENAI_MODEL", "")
            if profile_model and profile_model.lower() == low_model:
                return name

    return "-"


def load_session_categories() -> dict:
    """Load aweswitch sessions.json for category mapping."""
    path = os.path.expanduser("~/.config/aweswitch/sessions.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def get_category(session_id: str, categories: dict) -> str:
    """Get category for a session ID."""
    if not categories:
        return "-"
    return categories.get(session_id, {}).get("category", "-") or "-"
