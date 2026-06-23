"""Process status and metrics via ps."""

import subprocess
import sys
from typing import Optional


def get_process_info(pid: int) -> Optional[dict]:
    """Get CPU%, RSS memory (KB), and start time for a process.

    Returns None if process not found.
    """
    if pid <= 0:
        return None

    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "%cpu=,rss=,lstart="],
                capture_output=True,
                text=True,
                timeout=2,
            )
        else:
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
