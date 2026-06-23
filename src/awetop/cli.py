"""awetop CLI — profile-aware Claude Code session monitor."""

import json
import signal
import sys
import time

import click

from .discovery import find_session_files
from .pricing import compute_cost, load_custom_pricing, load_litellm_pricing
from .process import get_process_info, is_process_alive
from .profile import get_category, load_aweswitch_profiles, load_session_categories
from .render import render_table
from .snapshot import Session, Snapshot, Tokens
from .transcript import compute_context_pct, infer_status, parse_transcript


def build_snapshot() -> Snapshot:
    """Build a full snapshot of all Claude Code sessions."""
    # Load pricing and profile data once
    litellm = load_litellm_pricing()
    custom = load_custom_pricing()
    aweswitch_config = load_aweswitch_profiles()
    categories = load_session_categories()

    files = find_session_files()
    sessions = []

    for f in files:
        session_id = f["session_id"]
        file_path = f["file_path"]

        # Parse transcript (lightweight)
        tx = parse_transcript(file_path)
        tokens = tx["tokens"]
        model = tx["model"]

        # Process info
        # Try to get PID from the first line of JSONL
        pid = _extract_pid(file_path)
        proc = get_process_info(pid) if pid else None
        alive = proc is not None

        # Status
        status = infer_status(
            alive=alive,
            last_role=tx["last_role"],
            has_pending_tool_use=tx["has_pending_tool_use"],
            cpu_pct=proc["cpu_pct"] if proc else 0.0,
        )

        # CPU / memory
        cpu_pct = proc["cpu_pct"] if proc else 0.0
        mem_mb = (proc["mem_kb"] / 1024.0) if proc else 0.0

        # Context %
        context_pct = compute_context_pct(tokens, model)

        # Cost
        cost = compute_cost(tokens, model, litellm, custom)

        # Elapsed
        elapsed = _estimate_elapsed(proc, file_path)

        # Profile & category
        from .profile import match_profile

        profile = match_profile(model, aweswitch_config)
        category = get_category(session_id, categories)

        sessions.append(
            Session(
                session_id=session_id,
                pid=pid,
                model=model,
                status=status,
                profile=profile,
                category=category,
                tokens=tokens,
                context_pct=context_pct,
                cpu_pct=cpu_pct,
                mem_mb=mem_mb,
                cost_usd=cost,
                elapsed_secs=elapsed,
                file_path=file_path,
            )
        )

    # Filter out stopped sessions
    sessions = [s for s in sessions if s.status != "stopped"]

    # Sort: running first, then by token total descending
    status_order = {"running": 0, "waiting": 1, "idle": 2}
    sessions.sort(key=lambda s: (status_order.get(s.status, 9), -s.tokens.total))

    return Snapshot.from_sessions(sessions)


def _extract_pid(file_path: str) -> int:
    """Extract PID from the first line of a JSONL session file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if first_line:
                entry = json.loads(first_line)
                pid = entry.get("pid", 0)
                if isinstance(pid, int) and pid > 0:
                    return pid
    except (OSError, json.JSONDecodeError):
        pass
    return 0


def _estimate_elapsed(proc: dict, file_path: str) -> int:
    """Estimate elapsed seconds from process start time or file mtime."""
    if proc and proc.get("start_str"):
        # ps lstart format is like "Mon Jun 23 10:30:00 2026"
        try:
            from datetime import datetime

            # Parse the ps lstart format
            start = datetime.strptime(proc["start_str"], "%a %b %d %H:%M:%S %Y")
            elapsed = (datetime.now() - start).total_seconds()
            return max(0, int(elapsed))
        except (ValueError, TypeError):
            pass

    # Fallback: file modification time
    try:
        import os

        mtime = os.path.getmtime(file_path)
        return max(0, int(time.time() - mtime))
    except OSError:
        return 0


@click.group(invoke_without_command=True)
@click.pass_context
@click.option("--json", "json_output", is_flag=True, help="Output JSON snapshot")
@click.option("--once", is_flag=True, help="Print once and exit (no watch)")
@click.version_option(version="0.1.0", prog_name="awetop")
def main(ctx, json_output, once):
    """Profile-aware Claude Code session monitor."""
    if ctx.invoked_subcommand is not None:
        return

    if json_output:
        snapshot = build_snapshot()
        click.echo(json.dumps(snapshot.to_dict(), indent=2))
        return

    if once:
        snapshot = build_snapshot()
        click.echo(render_table(snapshot))
        return

    # Watch mode (default)
    _watch()


def _watch():
    """Live watch loop with 2-second refresh."""
    # Handle Ctrl-C gracefully
    running = True

    def on_sigint(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, on_sigint)

    while running:
        snapshot = build_snapshot()
        # Clear screen and render
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.write(render_table(snapshot))
        sys.stdout.write("\n")
        sys.stdout.write(f"\033[90mCtrl-C to exit\033[0m")
        sys.stdout.flush()

        # Sleep in 100ms slices for responsive Ctrl-C
        for _ in range(20):
            if not running:
                break
            time.sleep(0.1)

    # Clean exit
    sys.stdout.write("\n")
    sys.stdout.flush()
