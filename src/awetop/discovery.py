"""Discover Claude Code session files from ~/.claude/projects."""

import glob
import os
from pathlib import Path


def find_session_files(claude_home: str = "") -> list[dict]:
    """Find all JSONL session files under ~/.claude/projects.

    Claude Code stores sessions as JSONL files either:
    - Directly in project dir: ~/.claude/projects/<project>/<session>.jsonl
    - In a sessions subdir: ~/.claude/projects/<project>/sessions/<session>.jsonl

    Returns list of dicts with: session_id, project_name, file_path
    """
    if not claude_home:
        claude_home = os.path.expanduser("~/.claude")

    projects_dir = os.path.join(claude_home, "projects")
    if not os.path.isdir(projects_dir):
        return []

    sessions = []

    # Pattern 1: ~/.claude/projects/<project>/<session>.jsonl
    pattern_direct = os.path.join(projects_dir, "*", "*.jsonl")
    for path in glob.glob(pattern_direct):
        project_name = Path(path).parent.name
        session_id = Path(path).stem
        sessions.append(
            {
                "session_id": session_id,
                "project_name": project_name,
                "file_path": path,
            }
        )

    # Pattern 2: ~/.claude/projects/<project>/sessions/<session>.jsonl
    pattern_subdir = os.path.join(projects_dir, "*", "sessions", "*.jsonl")
    for path in glob.glob(pattern_subdir):
        project_name = Path(path).parent.parent.name
        session_id = Path(path).stem
        sessions.append(
            {
                "session_id": session_id,
                "project_name": project_name,
                "file_path": path,
            }
        )

    return sessions
