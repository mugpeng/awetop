"""Data structures for session snapshots."""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Tokens:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_create: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_create


@dataclass
class Session:
    session_id: str
    pid: Optional[int] = None
    model: str = ""
    status: str = "unknown"  # running, waiting, idle, stopped
    profile: str = "-"
    category: str = "-"
    tokens: Tokens = field(default_factory=Tokens)
    context_pct: float = 0.0
    cpu_pct: float = 0.0
    mem_mb: float = 0.0
    cost_usd: Optional[float] = None
    elapsed_secs: int = 0
    file_path: str = ""


@dataclass
class Snapshot:
    generated_at: str = ""
    sessions: list = field(default_factory=list)
    total_sessions: int = 0
    active_sessions: int = 0
    total_cost_usd: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # Remove None cost fields for cleaner JSON
        for s in d["sessions"]:
            if s["cost_usd"] is None:
                del s["cost_usd"]
        if d["total_cost_usd"] is None:
            del d["total_cost_usd"]
        return d

    @classmethod
    def from_sessions(cls, sessions: list[Session]) -> "Snapshot":
        total_cost = 0.0
        has_cost = False
        for s in sessions:
            if s.cost_usd is not None:
                total_cost += s.cost_usd
                has_cost = True

        return cls(
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            sessions=sessions,
            total_sessions=len(sessions),
            active_sessions=sum(
                1 for s in sessions if s.status in ("running", "waiting")
            ),
            total_cost_usd=total_cost if has_cost else None,
        )
