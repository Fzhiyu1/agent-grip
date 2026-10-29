"""Pi and Pi-format harnesses: ~/.pi/agent/sessions/<slug>/<timestamp>_<id>.jsonl.

Two traps found on real data, both handled here:

1. Pi forks a session by copying it into a new file, so the same user message appears in several
   files. Files are read oldest-first and a message is credited to the first file that contains it
   (key = timestamp to 0.1 s + a hash of the text).
2. Orchestrators (Orca, goal mode, skill loaders) write their dispatches as user messages. The log
   has no attribution field, so these are removed by prefix and the rest is graded C (heuristic).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import List, Optional, Set, Tuple

from ..model import Collector, SourceInfo
from ..textclean import auto_prefix
from ..util import glob_files, parse_iso
from .base import Adapter, Progress, env_path

# Messages written by orchestration tooling, not typed by the user.
ORCHESTRATION_PREFIXES = (
    "Task:", "You are working inside Orca", "--- Orchestration Messages", "Goal mode is active",
    "<skill name=", "<skill ", "Base directory for this skill:",
)


_IS_SESSION = re.compile(r'"type"\s*:\s*"session"')
_IS_MESSAGE = re.compile(r'"type"\s*:\s*"message"')


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        b.get("text", "") for b in (content or []) if isinstance(b, dict) and b.get("type") == "text"
    )


class PiAdapter(Adapter):
    id = "pi"
    label = "Pi"
    attribution = "heuristic (orchestrator prefixes removed, forked copies de-duplicated)"
    sessions_dirname = ("agent", "sessions")
    home_dirname = ".pi"

    def roots(self) -> List[Path]:
        base = env_path("PI_CODING_AGENT_DIR")
        if base:
            return [base / "sessions"]
        return [self.home / self.home_dirname / Path(*self.sessions_dirname)]

    def scan(self, col: Collector, progress: Optional[Progress] = None) -> None:
        files: List[Path] = []
        for r in self.roots():
            files += glob_files(r, "*/*.jsonl")
        files.sort(key=lambda p: p.name)
        seen: Set[Tuple[float, str]] = set()
        for i, f in enumerate(files):
            if progress and i % 100 == 0:
                progress(f"{self.id} {i}/{len(files)}")
            try:
                self._file(col, f, seen)
            except OSError as e:
                col.warnings.append(f"{self.id}: cannot read {f.name}: {e}")
        col.sources.append(SourceInfo(self.id, self.label, len(files), "forked copies de-duplicated; orchestrator prefixes removed"))

    def _file(self, col: Collector, f: Path, seen: Set[Tuple[float, str]]) -> None:
        sid = f.stem.split("_", 1)[-1]
        ctx = None
        with open(f, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                head = line[:200]
                if _IS_SESSION.search(head):
                    try:
                        o = json.loads(line)
                    except ValueError:
                        return
                    sid = o.get("id") or sid
                    ctx = col.session(self.id, sid, cwd=o.get("cwd"))
                    if ctx is None:
                        return
                    continue
                if not _IS_MESSAGE.search(head):
                    continue
                if ctx is None:
                    ctx = col.session(self.id, sid)
                    if ctx is None:
                        return
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                m = o.get("message") or {}
                role = m.get("role")
                try:
                    ts = float(m["timestamp"]) / 1000.0 if m.get("timestamp") else parse_iso(o["timestamp"])
                    if ts < 1e9:
                        ts = parse_iso(o["timestamp"])
                except Exception:
                    continue
                if role == "assistant":
                    content = m.get("content") or []
                    n_tool = sum(1 for b in content if isinstance(b, dict) and b.get("type") == "toolCall")
                    if m.get("stopReason") == "aborted":
                        ctx.event(ts, "interrupt")
                    elif n_tool:
                        for _ in range(n_tool):
                            ctx.event(ts, "tool")
                    else:
                        ctx.event(ts, "agent")
                elif role == "toolResult":
                    ctx.event(ts, "agent")
                elif role == "user":
                    text = _text(m.get("content"))
                    if not text.strip():
                        continue
                    key = (round(ts, 1), hashlib.sha1(text[:200].encode("utf-8", "replace")).hexdigest())
                    if key in seen:
                        ctx.skip("forked_duplicate", ts)
                        continue
                    seen.add(key)
                    lead = text.lstrip()
                    if lead.startswith(ORCHESTRATION_PREFIXES) or auto_prefix(text):
                        ctx.skip("orchestrator", ts)
                        continue
                    ctx.human(ts, text, "C")
        if ctx is not None:
            ctx.close()


class OmpAdapter(PiAdapter):
    id = "omp"
    label = "oh-my-pi"
    home_dirname = ".omp"

    def roots(self) -> List[Path]:
        return [self.home / ".omp" / "agent" / "sessions"]
