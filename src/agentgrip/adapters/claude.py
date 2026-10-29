"""Claude Code: ~/.claude/projects/<slug>/<id>.jsonl plus ~/.claude/history.jsonl.

projects/ holds full transcripts but old ones get cleaned up; history.jsonl keeps every prompt you
typed (the shell-style prompt history), so it back-fills sessions that no longer have a transcript.
A session present in both is counted once, from the transcript.

Attribution: transcripts mark subagent traffic (isSidechain) and injected meta turns (isMeta), and
tool results come back as user-role entries with tool_result blocks. After removing those, the
remainder is typed by a human (grade B). history.jsonl entries are typed prompts by construction (grade B).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..model import Collector, SourceInfo
from ..textclean import auto_prefix, is_slash_command
from ..util import glob_files, parse_iso
from .base import Adapter, Progress, env_path


# cheap pre-filter: skip lines that cannot be user/assistant entries without parsing them.
# Whitespace-tolerant on purpose: a filter that depends on exact serialisation drops data silently.
_ENTRY = re.compile(r'"type"\s*:\s*"(user|assistant)"')


def _blocks(content):
    return content if isinstance(content, list) else []


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in _blocks(content) if isinstance(b, dict) and b.get("type") == "text")


class ClaudeAdapter(Adapter):
    id = "claude"
    label = "Claude Code"
    attribution = "structural (sidechain / meta / tool_result removed)"

    def _base(self) -> Path:
        return env_path("CLAUDE_CONFIG_DIR") or (self.home / ".claude")

    def roots(self) -> List[Path]:
        b = self._base()
        return [b / "projects", b / "history.jsonl"]

    def scan(self, col: Collector, progress: Optional[Progress] = None) -> None:
        files = glob_files(self._base() / "projects", "*/*.jsonl")
        seen: Set[str] = set()
        for i, f in enumerate(files):
            if progress and i % 50 == 0:
                progress(f"claude transcripts {i}/{len(files)}")
            seen.add(f.stem)
            try:
                self._transcript(col, f)
            except OSError as e:
                col.warnings.append(f"claude: cannot read {f.name}: {e}")
        n_hist = self._history(col, seen)
        col.sources.append(
            SourceInfo(self.id, self.label, len(files), f"{n_hist} prompts from history.jsonl for sessions without a transcript")
        )

    def _transcript(self, col: Collector, f: Path) -> None:
        sid = f.stem
        ctx = None
        first = True
        with open(f, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not _ENTRY.search(line):
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                t = o.get("type")
                if t not in ("user", "assistant"):
                    continue
                if first:
                    first = False
                    excl = "non_interactive_sdk" if o.get("entrypoint") == "sdk-cli" else None
                    ctx = col.session(self.id, sid, cwd=o.get("cwd"), exclude=excl)
                    if ctx is None:
                        return
                try:
                    ts = parse_iso(o["timestamp"])
                except Exception:
                    continue
                if o.get("isSidechain"):
                    ctx.event(ts, "agent")
                    continue
                msg = o.get("message") or {}
                content = msg.get("content")
                if t == "assistant":
                    n_tool = sum(1 for b in _blocks(content) if isinstance(b, dict) and b.get("type") == "tool_use")
                    if n_tool:
                        for _ in range(n_tool):
                            ctx.event(ts, "tool")
                    else:
                        ctx.event(ts, "agent")
                    continue
                if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in _blocks(content)):
                    ctx.event(ts, "agent")
                    continue
                if o.get("isMeta"):
                    ctx.skip("meta", ts)
                    continue
                text = _text(content)
                if not text.strip():
                    continue
                if text.lstrip().startswith("[Request interrupted"):
                    ctx.event(ts, "interrupt")
                    continue
                if auto_prefix(text):
                    ctx.skip("injected", ts)
                    continue
                if is_slash_command(text):
                    ctx.skip("slash_command", ts)
                    continue
                ctx.human(ts, text, "B")
        if ctx is not None:
            ctx.close()

    def _history(self, col: Collector, seen: Set[str]) -> int:
        h = self._base() / "history.jsonl"
        if not h.exists():
            return 0
        by_sid: Dict[str, List] = {}
        with open(h, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                    sid, ts = o["sessionId"], o["timestamp"] / 1000.0
                except (ValueError, KeyError, TypeError):
                    continue
                if sid in seen:
                    continue
                by_sid.setdefault(sid, []).append((ts, o.get("display") or "", o.get("project")))
        n = 0
        for sid, rows in by_sid.items():
            rows.sort(key=lambda r: r[0])
            ctx = col.session(self.id, sid, cwd=rows[0][2])
            if ctx is None:
                continue
            for ts, text, _ in rows:
                if not text.strip():
                    continue
                if is_slash_command(text) or auto_prefix(text):
                    ctx.skip("slash_command", ts)
                    continue
                if ctx.human(ts, text, "B"):
                    n += 1
            ctx.close()
        return n
