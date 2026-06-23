"""Process-first session discovery for Claude Code and Codex CLI.

Strategy:
1. Snapshot all processes via ps
2. Find running claude/codex PIDs
3. Map PIDs to open files via lsof
4. Resolve session files from open paths
5. Fallback: scan for recently-active session files
"""

import glob
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional


def find_active_sessions() -> list[dict]:
    """Find all active Claude Code and Codex CLI sessions.

    Returns list of dicts with: session_id, agent, project_name, file_path, pid
    """
    from .process import get_all_processes

    procs = get_all_processes()
    sessions = []

    # Find claude and codex PIDs
    claude_pids = []
    codex_pids = []
    for pid, info in procs.items():
        cmd = info["command"]
        if _cmd_matches(cmd, "claude"):
            claude_pids.append(pid)
        elif _cmd_matches(cmd, "codex"):
            codex_pids.append(pid)

    # Map PIDs to session files
    for pid in claude_pids:
        s = _resolve_claude_session(pid)
        if s:
            sessions.append(s)

    for pid in codex_pids:
        s = _resolve_codex_session(pid)
        if s:
            sessions.append(s)

    # Fallback: recently-active session files (mtime < 2 min)
    # for sessions not matched to a running process
    seen_ids = {s["session_id"] for s in sessions}
    seen_paths = {s["file_path"] for s in sessions}
    for s in _find_recently_active_sessions(exclude_paths=seen_paths):
        if s["session_id"] not in seen_ids:
            sessions.append(s)

    return sessions


def _cmd_matches(cmd: str, binary: str) -> bool:
    """Check if a command string matches a binary name."""
    if not cmd:
        return False
    # Check first two tokens (handles env wrappers like /usr/bin/env claude)
    tokens = cmd.split()[:2]
    for token in tokens:
        basename = os.path.basename(token)
        # Strip .exe for Windows
        if basename.endswith(".exe"):
            basename = basename[:-4]
        if basename == binary:
            return True
        # Handle autoupdater: ~/.local/share/claude/versions/X.Y.Z
        parts = token.split("/")
        if len(parts) >= 3 and parts[-2] == "versions":
            if os.path.basename(parts[-3]) == binary:
                return True
    return False


def _lsof_open_files(pid: int) -> list[str]:
    """Get list of open file paths for a PID via lsof."""
    try:
        result = subprocess.run(
            ["lsof", "-F", "pn", f"-p{pid}"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    paths = []
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            paths.append(line[1:])
    return paths


def _resolve_claude_session(pid: int) -> Optional[dict]:
    """Resolve a claude PID to a session dict."""
    open_paths = _lsof_open_files(pid)

    # Find config roots from open paths
    config_roots = set()
    for path in open_paths:
        root = _config_root_from_path(path)
        if root:
            config_roots.add(root)

    # Also check default and sibling dirs
    config_roots.update(_discover_config_dirs())

    for root in config_roots:
        session = _load_claude_session(root, pid)
        if session:
            return session

    return None


def _config_root_from_path(path: str) -> Optional[str]:
    """Walk up a path looking for a Claude config root (has sessions/ and projects/)."""
    p = Path(path)
    for ancestor in p.parents:
        try:
            if (ancestor / "sessions").is_dir() and (ancestor / "projects").is_dir():
                return str(ancestor)
        except PermissionError:
            continue
    return None


def _discover_config_dirs() -> set[str]:
    """Find all Claude config directories: ~/.claude and ~/.claude-*."""
    home = os.path.expanduser("~")
    dirs = set()

    default = os.path.join(home, ".claude")
    if _is_claude_config_root(default):
        dirs.add(default)

    # Scan for sibling profiles
    try:
        for entry in os.listdir(home):
            if entry.startswith(".claude-") and entry != ".claude":
                path = os.path.join(home, entry)
                if os.path.isdir(path) and _is_claude_config_root(path):
                    dirs.add(path)
    except OSError:
        pass

    return dirs


def _is_claude_config_root(path: str) -> bool:
    """Check if a directory has sessions/ and projects/ subdirs."""
    try:
        return os.path.isdir(os.path.join(path, "sessions")) and os.path.isdir(
            os.path.join(path, "projects")
        )
    except PermissionError:
        return False


def _load_claude_session(config_dir: str, pid: int) -> Optional[dict]:
    """Load a Claude session for a given PID from a config dir."""
    sessions_dir = os.path.join(config_dir, "sessions")

    # Direct lookup: sessions/{PID}.json
    pid_file = os.path.join(sessions_dir, f"{pid}.json")
    if os.path.isfile(pid_file):
        meta = _read_session_meta(pid_file)
        if meta:
            session_id = meta.get("sessionId", "")
            cwd = meta.get("cwd", "")
            if session_id:
                transcript = _find_claude_transcript(
                    config_dir, session_id, cwd
                )
                if transcript:
                    project = _short_project_name(cwd or config_dir)
                    return {
                        "session_id": session_id,
                        "agent": "claude",
                        "project_name": project,
                        "file_path": transcript,
                        "pid": pid,
                    }

    # Fallback: scan all session JSONs for matching PID
    try:
        for entry in os.scandir(sessions_dir):
            if entry.name.endswith(".json") and entry.is_file():
                meta = _read_session_meta(entry.path)
                if meta and meta.get("pid") == pid:
                    session_id = meta.get("sessionId", "")
                    cwd = meta.get("cwd", "")
                    if session_id:
                        transcript = _find_claude_transcript(
                            config_dir, session_id, cwd
                        )
                        if transcript:
                            project = _short_project_name(cwd or config_dir)
                            return {
                                "session_id": session_id,
                                "agent": "claude",
                                "project_name": project,
                                "file_path": transcript,
                                "pid": pid,
                            }
    except OSError:
        pass

    return None


def _read_session_meta(path: str) -> Optional[dict]:
    """Read a Claude session JSON file."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _encode_cwd(cwd: str) -> str:
    """Encode a cwd path like Claude does for project directory names.

    Replaces /, \\, :, _, . with - (but preserves leading -).
    """
    if not cwd:
        return ""
    encoded = cwd
    for ch in "/\\:_.":
        encoded = encoded.replace(ch, "-")
    # Collapse multiple dashes
    while "--" in encoded:
        encoded = encoded.replace("--", "-")
    return encoded.strip("-")


def _find_claude_transcript(
    config_dir: str, session_id: str, cwd: str
) -> Optional[str]:
    """Find the JSONL transcript file for a Claude session."""
    projects_dir = os.path.join(config_dir, "projects")

    if cwd:
        encoded = _encode_cwd(cwd)
        candidate = os.path.join(projects_dir, encoded, f"{session_id}.jsonl")
        if os.path.isfile(candidate):
            return candidate

    # Fallback: scan project dirs
    try:
        for entry in os.scandir(projects_dir):
            if entry.is_dir():
                path = os.path.join(entry.path, f"{session_id}.jsonl")
                if os.path.isfile(path):
                    return path
    except OSError:
        pass

    return None


def _resolve_codex_session(pid: int) -> Optional[dict]:
    """Resolve a codex PID to a session dict."""
    open_paths = _lsof_open_files(pid)

    # Look for rollout-*.jsonl in open files
    for path in open_paths:
        basename = os.path.basename(path)
        if basename.startswith("rollout-") and basename.endswith(".jsonl"):
            return _load_codex_session(path, pid)

    return None


def _load_codex_session(file_path: str, pid: int = 0) -> Optional[dict]:
    """Load session info from a Codex rollout JSONL file."""
    try:
        with open(file_path, "r") as f:
            first_line = f.readline().strip()
            if not first_line:
                return None
            entry = json.loads(first_line)
            if entry.get("type") != "session_meta":
                return None
            payload = entry.get("payload", {})
            session_id = payload.get("id", "")
            cwd = payload.get("cwd", "")
            if not session_id:
                return None
            project = _short_project_name(cwd)
            return {
                "session_id": session_id,
                "agent": "codex",
                "project_name": project,
                "file_path": file_path,
                "pid": pid,
            }
    except (OSError, json.JSONDecodeError):
        return None


def _find_recently_active_sessions(exclude_paths: set[str] = None) -> list[dict]:
    """Find session files modified within the last 2 minutes.

    Fallback for sessions whose processes we didn't catch.
    exclude_paths: set of file paths already resolved (to avoid duplicates).
    """
    if exclude_paths is None:
        exclude_paths = set()

    sessions = []
    now = time.time()
    max_age = 120  # 2 minutes

    # Claude sessions
    for root in _discover_config_dirs():
        projects_dir = os.path.join(root, "projects")
        if not os.path.isdir(projects_dir):
            continue
        try:
            for project_entry in os.scandir(projects_dir):
                if not project_entry.is_dir():
                    continue
                for jsonl in os.scandir(project_entry.path):
                    if not jsonl.name.endswith(".jsonl"):
                        continue
                    if jsonl.path in exclude_paths:
                        continue
                    try:
                        mtime = jsonl.stat().st_mtime
                        if now - mtime > max_age:
                            continue
                        session_id = Path(jsonl.name).stem
                        project_name = project_entry.name
                        sessions.append({
                            "session_id": session_id,
                            "agent": "claude",
                            "project_name": project_name,
                            "file_path": jsonl.path,
                            "pid": 0,
                        })
                    except OSError:
                        continue
        except OSError:
            continue

    # Codex sessions
    codex_sessions_dir = os.path.expanduser("~/.codex/sessions")
    if os.path.isdir(codex_sessions_dir):
        try:
            today = time.strftime("%Y/%m/%d")
            today_dir = os.path.join(codex_sessions_dir, today)
            if os.path.isdir(today_dir):
                for entry in os.scandir(today_dir):
                    if not entry.name.startswith("rollout-") or not entry.name.endswith(".jsonl"):
                        continue
                    if entry.path in exclude_paths:
                        continue
                    try:
                        mtime = entry.stat().st_mtime
                        if now - mtime > max_age:
                            continue
                        s = _load_codex_session(entry.path)
                        if s:
                            sessions.append(s)
                    except OSError:
                        continue
        except OSError:
            pass

    return sessions


def _short_project_name(path: str) -> str:
    """Get a short project name from a path (last directory component)."""
    if not path:
        return "-"
    name = os.path.basename(path.rstrip("/"))
    return name if name else "-"
