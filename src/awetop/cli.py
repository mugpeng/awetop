"""awetop CLI — profile-aware Claude Code & Codex session monitor."""

import json
import signal
import sys
import time

import click

from .discovery import find_active_sessions
from .pricing import compute_cost, load_custom_pricing, load_litellm_pricing
from .process import get_all_processes
from .profile import get_category, load_aweswitch_profiles, match_profile, load_session_categories
from .render import render_table
from .snapshot import Session, Snapshot, Tokens
from .transcript import (
    compute_context_pct,
    infer_status,
    parse_codex_transcript,
    parse_transcript,
)


def build_snapshot() -> Snapshot:
    """Build a full snapshot of all active Claude Code and Codex sessions."""
    litellm = load_litellm_pricing()
    custom = load_custom_pricing()
    aweswitch_config = load_aweswitch_profiles()
    categories = load_session_categories()

    # Batch process info (single ps call)
    procs = get_all_processes()

    discovered = find_active_sessions()
    sessions = []

    for d in discovered:
        session_id = d["session_id"]
        file_path = d["file_path"]
        agent = d.get("agent", "claude")
        pid = d.get("pid", 0)
        project_name = d.get("project_name", "-")

        # Parse transcript based on agent type
        if agent == "codex":
            tx = parse_codex_transcript(file_path)
        else:
            tx = parse_transcript(file_path)

        tokens = tx["tokens"]
        model = tx["model"]

        # Process info from batch snapshot
        proc = procs.get(pid) if pid else None
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

        # Profile & category (aweswitch, claude only)
        profile = match_profile(model, aweswitch_config) if agent == "claude" else "-"
        category = get_category(session_id, categories) if agent == "claude" else "-"

        sessions.append(
            Session(
                session_id=session_id,
                pid=pid,
                agent=agent,
                model=model,
                status=status,
                profile=profile,
                category=category,
                project=project_name,
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

    # Sort: thinking/executing first, then by token total descending
    status_order = {"thinking": 0, "executing": 1, "waiting": 2, "idle": 3}
    sessions.sort(key=lambda s: (status_order.get(s.status, 9), -s.tokens.total))

    return Snapshot.from_sessions(sessions)


def _estimate_elapsed(proc: dict, file_path: str) -> int:
    """Estimate elapsed seconds from file mtime."""
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
    """Profile-aware Claude Code & Codex session monitor."""
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
    running = True

    def on_sigint(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, on_sigint)

    while running:
        snapshot = build_snapshot()
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.write(render_table(snapshot))
        sys.stdout.write("\n")
        sys.stdout.flush()

        for _ in range(20):
            if not running:
                break
            time.sleep(0.1)

    sys.stdout.write("\n")
    sys.stdout.flush()
