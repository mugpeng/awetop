"""ANSI table rendering for terminal output."""

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
_BLUE = "\033[34m"
_CYAN = "\033[36m"
_GRAY = "\033[90m"


def _color_status(status: str) -> str:
    colors = {
        "running": f"{_CYAN}{status}{_RESET}",
        "waiting": f"{_YELLOW}{status}{_RESET}",
        "idle": f"{_GREEN}{status}{_RESET}",
        "stopped": f"{_GRAY}{status}{_RESET}",
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


def _format_uptime(secs: int) -> str:
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    h = secs // 3600
    m = (secs % 3600) // 60
    return f"{h}h{m}m"


def _pad(s: str, width: int) -> str:
    # Simple padding (doesn't account for ANSI escape widths, good enough)
    visible = s
    for code in [_RESET, _BOLD, _DIM, _RED, _GREEN, _YELLOW, _BLUE, _CYAN, _GRAY]:
        visible = visible.replace(code, "")
    padding = max(0, width - len(visible))
    return s + " " * padding


def render_table(snapshot: Snapshot) -> str:
    """Render sessions as an ANSI table."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []

    # Header
    header = (
        f"{_BOLD}awetop{_RESET} — "
        f"{snapshot.total_sessions} sessions "
        f"({snapshot.active_sessions} active) — "
        f"{now}"
    )
    lines.append(header)
    lines.append("")

    if not snapshot.sessions:
        lines.append(f"{_DIM}No Claude Code sessions found.{_RESET}")
        return "\n".join(lines)

    # Column headers
    cols = [
        ("STATUS", 9),
        ("PROFILE", 13),
        ("CATEGORY", 11),
        ("MODEL", 20),
        ("TOKENS(IN/OUT)", 16),
        ("CTX%", 6),
        ("CPU", 7),
        ("MEM", 8),
        ("COST", 9),
        ("UPTIME", 8),
    ]

    header_line = "  ".join(_pad(f"{_BOLD}{name}{_RESET}", w) for name, w in cols)
    lines.append(header_line)

    for s in snapshot.sessions:
        row = [
            _pad(_color_status(s.status), cols[0][1]),
            _pad(s.profile, cols[1][1]),
            _pad(s.category, cols[2][1]),
            _pad(s.model[:19] if s.model else "-", cols[3][1]),
            _pad(_format_tokens(s.tokens), cols[4][1]),
            _pad(f"{s.context_pct:.0f}%", cols[5][1]),
            _pad(f"{s.cpu_pct:.1f}%", cols[6][1]),
            _pad(f"{s.mem_mb:.0f}M", cols[7][1]),
            _pad(_format_cost(s.cost_usd), cols[8][1]),
            _pad(_format_uptime(s.elapsed_secs), cols[9][1]),
        ]
        lines.append("  ".join(row))

    # Footer with totals
    if snapshot.total_cost_usd is not None:
        lines.append("")
        lines.append(
            f"{_DIM}Total cost: {_format_cost(snapshot.total_cost_usd)}{_RESET}"
        )

    return "\n".join(lines)
