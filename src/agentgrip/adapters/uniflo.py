"""Optional bridge to uniflo (https://github.com/Crosery/uniflo): one adapter, ~30 more AI tools.

uniflo normalises sessions of Claude Code, Codex, Gemini CLI, OpenCode, dsh, Cursor, ... into one event
format. This adapter shells out to the `uniflo` binary (read-only subcommands `ls` and `tail --json`,
with --local so no daemon is touched) for every tool that does NOT already have a dedicated adapter
in this package. Dedicated adapters stay authoritative because they use richer attribution than
uniflo's single `synthetic` flag (e.g. Codex turn_trigger).

Attribution is grade C: a uniflo `user_message` that is not `synthetic` is treated as human, and
subagent sessions (those with a `parent`) are dropped.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Dict, List, Optional, Set

from ..model import Collector, SourceInfo
from .base import Adapter, Progress

# harness ids that have a dedicated adapter here: uniflo must not double-count them
DEDICATED = {"codex", "claude", "pi", "omp"}


class UnifloAdapter(Adapter):
    id = "uniflo"
    label = "uniflo (other tools)"
    attribution = "heuristic (uniflo `synthetic` flag only)"
    binary_name = "uniflo"

    def _bin(self) -> Optional[str]:
        return shutil.which(self.binary_name)

    def roots(self):
        return []

    def detect(self) -> bool:
        return self._bin() is not None

    def _run(self, args: List[str], timeout: int = 120) -> Optional[str]:
        exe = self._bin()
        if not exe:
            return None
        try:
            r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return r.stdout if r.returncode == 0 else None

    def scan(self, col: Collector, progress: Optional[Progress] = None) -> None:
        out = self._run(["ls", "--local", "-n", "100000", "--json"], timeout=300)
        if out is None:
            col.warnings.append("uniflo: `uniflo ls --local --json` failed; skipped")
            return
        try:
            sessions = json.loads(out)
        except ValueError:
            col.warnings.append("uniflo: could not parse `uniflo ls` output; skipped")
            return
        todo = [s for s in sessions if s.get("harness") not in DEDICATED and not s.get("parent")]
        per_tool: Dict[str, int] = {}
        for i, s in enumerate(todo):
            if progress and i % 25 == 0:
                progress(f"uniflo {i}/{len(todo)}")
            tool = s["harness"]
            raw = self._run(["tail", "--local", "--json", "-n", "100000", s["key"]], timeout=120)
            if raw is None:
                col.warnings.append(f"uniflo: could not read {s['key']}")
                continue
            ctx = col.session(tool, s["id"], cwd=s.get("cwd"))
            if ctx is None:
                continue
            per_tool[tool] = per_tool.get(tool, 0) + 1
            for line in raw.splitlines():
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                e = o.get("event", o)
                ts = (e.get("ts") or 0) / 1000.0
                if not ts:
                    continue
                k = e.get("kind")
                if k == "user_message":
                    if e.get("synthetic"):
                        ctx.skip("synthetic", ts)
                    else:
                        ctx.human(ts, e.get("text") or "", "C")
                elif k == "tool_call":
                    ctx.event(ts, "tool")
                elif k == "assistant_message":
                    ctx.event(ts, "agent")
                elif k == "turn_end" and e.get("reason") in ("interrupted", "aborted"):
                    ctx.event(ts, "interrupt")
            ctx.close()
        note = ", ".join(f"{t} {n}" for t, n in sorted(per_tool.items())) or "no extra tools found"
        col.sources.append(SourceInfo(self.id, self.label, len(todo), "via `uniflo ls/tail --json`; " + note))
