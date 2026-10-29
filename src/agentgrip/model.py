"""Data model and the Collector every adapter writes into."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Pattern, Sequence, Tuple

from .textclean import Feat, features, strip_context
from .util import is_temp_path

GRADE_TEXT = {
    "A": "explicit metadata says a human sent it",
    "B": "structural signal (client id, not a subagent, not synthetic)",
    "C": "heuristic only (this log has no attribution metadata)",
}


@dataclass(frozen=True)
class HumanMsg:
    ts: float
    session: str
    tool: str
    feat: Feat
    grade: str


@dataclass
class SessionStats:
    key: str
    tool: str
    human: int = 0
    tool_calls: int = 0
    interrupts: int = 0
    agent_events: int = 0
    has_events: bool = False
    first_ts: float = 0.0
    last_ts: float = 0.0
    spans: List[Tuple[float, float]] = field(default_factory=list)


@dataclass
class SourceInfo:
    tool: str
    label: str
    files: int
    note: str = ""


@dataclass
class Dataset:
    msgs: List[HumanMsg]
    sessions: Dict[str, SessionStats]
    audit: Dict[str, Counter]
    sources: List[SourceInfo]
    warnings: List[str]
    idle_gap: float


class SessionCtx:
    """Receives the time-ordered events of one session."""

    def __init__(self, col: "Collector", tool: str, sid: str):
        self.col, self.tool = col, tool
        self.stats = SessionStats(key=f"{tool}:{sid}", tool=tool)
        self._last_ts = 0.0
        self._last_human = -1e18
        self._span_start: Optional[float] = None
        self._span_last = 0.0

    def _touch(self, ts: float, human: bool) -> float:
        ts = max(ts, self._last_ts)
        self._last_ts = ts
        if not self.stats.first_ts:
            self.stats.first_ts = ts
        self.stats.last_ts = ts
        if self._span_start is not None and ts - self._span_last > self.col.idle_gap:
            self._close_span()
        if self._span_start is None:
            if human:
                self._span_start = self._span_last = ts
        else:
            self._span_last = ts
        return ts

    def _close_span(self) -> None:
        if self._span_start is not None and self._span_last > self._span_start:
            self.stats.spans.append((self._span_start, self._span_last))
        self._span_start = None

    def human(self, ts: float, text: str, grade: str) -> bool:
        """Offer a candidate user message. Returns True when it was kept as a human message."""
        a = self.col.audit[self.tool]
        stripped = strip_context(text)
        if text.strip() and not stripped:
            return self.skip("context_only", ts)
        for rx in self.col.extra_exclude:
            if rx.search(stripped):
                return self.skip("user_pattern", ts)
        if ts - self._last_human < self.col.merge_gap:
            return self.skip("burst_merged", ts)
        self._last_human = ts
        ts = self._touch(ts, True)
        self.stats.human += 1
        self.col.msgs.append(HumanMsg(ts, self.stats.key, self.tool, features(stripped), grade))
        a["human_kept"] += 1
        a["human_kept:" + grade] += 1
        return True

    def skip(self, reason: str, ts: Optional[float] = None) -> bool:
        """A user-role message that is NOT from a human (automation, injected, duplicate)."""
        self.col.audit[self.tool]["excluded:" + reason] += 1
        if ts:
            self._touch(ts, False)
        return False

    def event(self, ts: float, kind: str) -> None:
        """kind is 'tool' (tool call), 'agent' (assistant output) or 'interrupt' (user stopped the agent)."""
        self.stats.has_events = True
        self._touch(ts, False)
        if kind == "tool":
            self.stats.tool_calls += 1
        elif kind == "interrupt":
            self.stats.interrupts += 1
        else:
            self.stats.agent_events += 1

    def close(self) -> None:
        self._close_span()
        if self.stats.human or self.stats.has_events:
            self.col.sessions[self.stats.key] = self.stats

    def __enter__(self) -> "SessionCtx":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class Collector:
    def __init__(
        self,
        idle_gap: float = 600.0,
        merge_gap: float = 8.0,
        exclude_temp: bool = True,
        extra_exclude: Sequence[str] = (),
        since: Optional[float] = None,
    ):
        self.idle_gap, self.merge_gap = idle_gap, merge_gap
        self.exclude_temp = exclude_temp
        self.extra_exclude: List[Pattern[str]] = [re.compile(p) for p in extra_exclude]
        self.since = since
        self.msgs: List[HumanMsg] = []
        self.sessions: Dict[str, SessionStats] = {}
        self.audit: Dict[str, Counter] = defaultdict(Counter)
        self.sources: List[SourceInfo] = []
        self.warnings: List[str] = []

    def session(self, tool: str, sid: str, cwd: Optional[str] = None, exclude: Optional[str] = None) -> Optional[SessionCtx]:
        """Open a session. Returns None when the whole session is excluded (the reason is recorded)."""
        a = self.audit[tool]
        a["sessions_scanned"] += 1
        if exclude is None and self.exclude_temp and is_temp_path(cwd):
            exclude = "temp_dir"
        if exclude:
            a["sessions_excluded:" + exclude] += 1
            return None
        return SessionCtx(self, tool, sid)

    def finish(self) -> Dataset:
        msgs = sorted(self.msgs, key=lambda m: m.ts)
        if self.since is not None:
            msgs = [m for m in msgs if m.ts >= self.since]
        return Dataset(msgs, self.sessions, dict(self.audit), self.sources, self.warnings, self.idle_gap)
