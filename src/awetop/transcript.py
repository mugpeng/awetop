"""Lightweight JSONL transcript parsing.

Only extracts: token usage totals, model name, last message role.
Does NOT parse chat text, tool calls, or tool results.
"""

import json
from typing import Optional

from .snapshot import Tokens


def parse_transcript(file_path: str) -> dict:
    """Parse a Claude Code JSONL transcript for lightweight metrics.

    Returns dict with:
      - tokens: Tokens (accumulated usage)
      - model: str (last assistant model)
      - last_role: str (last message role: "user" or "assistant")
      - has_pending_tool_use: bool (assistant asked for tools, no result yet)
    """
    tokens = Tokens()
    model = ""
    last_role = ""
    last_assistant_has_tool_use = False
    last_user_is_tool_result = False

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = entry.get("type", "")

                # Extract usage from assistant messages
                if msg_type == "assistant":
                    message = entry.get("message", {})
                    usage = message.get("usage", {})
                    if usage:
                        # Claude reports cumulative totals in some versions,
                        # but we take the last known values
                        tokens.input = max(
                            tokens.input, usage.get("input_tokens", 0)
                        )
                        tokens.output = max(
                            tokens.output, usage.get("output_tokens", 0)
                        )
                        tokens.cache_read = max(
                            tokens.cache_read,
                            usage.get("cache_read_input_tokens", 0),
                        )
                        tokens.cache_create = max(
                            tokens.cache_create,
                            usage.get("cache_creation_input_tokens", 0),
                        )

                    # Track model from assistant messages
                    m = message.get("model", "")
                    if m:
                        model = m

                    # Check if assistant has tool_use blocks
                    content = message.get("content", [])
                    if isinstance(content, list):
                        last_assistant_has_tool_use = any(
                            isinstance(b, dict) and b.get("type") == "tool_use"
                            for b in content
                        )
                    else:
                        last_assistant_has_tool_use = False

                    last_role = "assistant"

                elif msg_type == "user":
                    message = entry.get("message", {})
                    content = message.get("content", [])
                    # Check if this is a tool_result (response to tool_use)
                    if isinstance(content, list):
                        last_user_is_tool_result = any(
                            isinstance(b, dict)
                            and b.get("type") == "tool_result"
                            for b in content
                        )
                    else:
                        last_user_is_tool_result = False

                    last_role = "user"

    except (OSError, PermissionError):
        pass

    return {
        "tokens": tokens,
        "model": model,
        "last_role": last_role,
        "has_pending_tool_use": last_assistant_has_tool_use
        and last_role == "assistant",
    }


def infer_status(
    alive: bool,
    last_role: str,
    has_pending_tool_use: bool,
    cpu_pct: float = 0.0,
) -> str:
    """Infer session status from process state and transcript position."""
    if not alive:
        return "stopped"
    if last_role == "user":
        return "running"  # model is thinking
    if has_pending_tool_use:
        if cpu_pct > 0.5:
            return "running"  # tool is executing
        return "waiting"  # waiting for tool result
    if cpu_pct > 0.5:
        return "running"
    return "idle"


# Known context window sizes
CONTEXT_WINDOWS = {
    "claude-opus-4-6": 200_000,
    "claude-opus-4-5": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
}

DEFAULT_CONTEXT_WINDOW = 200_000


def get_context_window(model: str) -> int:
    """Get context window size for a model."""
    # Try exact match first
    if model in CONTEXT_WINDOWS:
        return CONTEXT_WINDOWS[model]
    # Try lowercase
    low = model.lower()
    for key, val in CONTEXT_WINDOWS.items():
        if key in low:
            return val
    return DEFAULT_CONTEXT_WINDOW


def compute_context_pct(tokens: Tokens, model: str) -> float:
    """Compute context window fill percentage."""
    window = get_context_window(model)
    if window <= 0:
        return 0.0
    total = tokens.total
    return min(100.0, (total / window) * 100.0)
