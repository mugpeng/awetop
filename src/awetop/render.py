"""Top-style ANSI rendering for terminal output."""

from datetime import datetime
from typing import Optional

from .snapshot import Session, Snapshot


# ANSI color codes
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_MAGENTA = "\033[35m"
_CYAN = "\033[36m"
_GRAY = "\033[90m"
_WHITE = "\033[97m"

# Box-drawing characters
_H = "─"
_V = "│"
_TL = "┌"
_TR = "┐"
_BL = "└"
_BR = "┘"
_LJ = "├"
_RJ = "┤"


def _color_status(status: str) -> str:
    colors = {
        "thinking": f"{_CYAN}{status}{_RESET}",
        "executing": f"{_MAGENTA}{status}{_RESET}",
        "waiting": f"{_YELLOW}{status}{_RESET}",
        "idle": f"{_GREEN}{status}{_RESET}",
    }
    return colors.get(status, status)


def _format_tokens(tokens) -> str:
    def _fmt(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.0f}k"
        return str(n)

    return f"{_fmt(tokens.input)}/{_fmt(tokens.output)}"


def _format_cost(cost: Optional[float]) -> str:
    if cost is None:
        return "-"
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def _pad(s: str, width: int) -> str:
    visible = s
    for code in [_RESET, _BOLD, _DIM, _RED, _GREEN, _YELLOW, _MAGENTA, _CYAN, _GRAY, _WHITE]:
        visible = visible.replace(code, "")
    padding = max(0, width - len(visible))
    return s + " " * padding


def render_table(snapshot: Snapshot) -> str:
    """Render sessions as a top-style ANSI table."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []

    # Header
    lines.append(
        f"{_BOLD}awetop{_RESET} "
        f"{_DIM}—{_RESET} "
        f"{snapshot.total_sessions} sessions "
        f"({_GREEN}{snapshot.active_sessions} active{_RESET}) "
        f"{_DIM}—{_RESET} "
        f"{now}"
    )

    if not snapshot.sessions:
        lines.append("")
        lines.append(f"{_DIM}  No active sessions found.{_RESET}")
        return "\n".join(lines)

    # Column definitions
    cols = [
        ("AGENT", 7),
        ("STATUS", 10),
        ("PROJECT", 16),
        ("MODEL", 22),
        ("TOKENS(IN/OUT)", 16),
        ("CTX%", 6),
        ("COST", 9),
    ]

    # Content width: sum of column widths + 2-space gaps between columns
    content_w = sum(w for _, w in cols) + 2 * (len(cols) - 1)

    # Top border
    lines.append(f"{_DIM}{_TL}{_H * content_w}{_TR}{_RESET}")

    # Column headers
    header_parts = []
    for name, w in cols:
        header_parts.append(_pad(f"{_BOLD}{_WHITE}{name}{_RESET}", w))
    lines.append(f"{_DIM}{_V}{_RESET} {'  '.join(header_parts)} {_DIM}{_V}{_RESET}")

    # Separator
    lines.append(f"{_DIM}{_LJ}{_H * content_w}{_RJ}{_RESET}")

    # Session rows
    for s in snapshot.sessions:
        agent_str = _pad(s.agent, cols[0][1])
        status_str = _pad(_color_status(s.status), cols[1][1])
        project_str = _pad(s.project[: cols[2][1] - 1] if s.project else "-", cols[2][1])
        model_str = _pad(
            (s.model[: cols[3][1] - 1] if s.model else "-"),
            cols[3][1],
        )
        tokens_str = _pad(_format_tokens(s.tokens), cols[4][1])
        ctx_str = _pad(f"{s.context_pct:.0f}%", cols[5][1])
        cost_str = _pad(_format_cost(s.cost_usd), cols[6][1])

        row = f"{agent_str}  {status_str}  {project_str}  {model_str}  {tokens_str}  {ctx_str}  {cost_str}"
        lines.append(f"{_DIM}{_V}{_RESET} {row} {_DIM}{_V}{_RESET}")

    # Bottom border
    lines.append(f"{_DIM}{_BL}{_H * content_w}{_BR}{_RESET}")

    # Footer
    cost_line = ""
    if snapshot.total_cost_usd is not None:
        cost_line = f"  {_DIM}Total:{_RESET} {_format_cost(snapshot.total_cost_usd)}"
    lines.append(f"{cost_line}  {_DIM}Ctrl-C to exit{_RESET}")

    return "\n".join(lines)
