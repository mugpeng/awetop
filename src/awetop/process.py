"""Process status and metrics via ps."""

import subprocess
import sys
from typing import Optional


def get_all_processes() -> dict[int, dict]:
    """Snapshot all processes in a single ps call.

    Returns dict mapping PID -> {cpu_pct, mem_kb, command, ppid}.
    """
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,%cpu=,rss=,command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {}
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}

    procs = {}
    for line in result.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
            cpu = float(parts[2])
            rss = int(parts[3])
            cmd = parts[4]
            procs[pid] = {
                "cpu_pct": cpu,
                "mem_kb": rss,
                "ppid": ppid,
                "command": cmd,
            }
        except (ValueError, IndexError):
            continue
    return procs


def get_process_info(pid: int) -> Optional[dict]:
    """Get CPU%, RSS memory (KB), and start time for a process.

    Returns None if process not found.
    """
    if pid <= 0:
        return None

    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "%cpu=,rss=,lstart="],
            capture_output=True,
            text=True,
            timeout=2,
        )

        if result.returncode != 0:
            return None

        line = result.stdout.strip()
        if not line:
            return None

        parts = line.split(None, 2)
        if len(parts) < 2:
            return None

        cpu_pct = float(parts[0])
        rss_kb = int(parts[1])
        start_str = parts[2] if len(parts) > 2 else ""

        return {
            "cpu_pct": cpu_pct,
            "mem_kb": rss_kb,
            "start_str": start_str,
        }
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        return None


def is_process_alive(pid: int) -> bool:
    """Check if a process is still running."""
    if pid <= 0:
        return False
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid)],
            capture_output=True,
            timeout=2,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
