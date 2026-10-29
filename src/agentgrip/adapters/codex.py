"""OpenAI Codex (CLI and desktop app): ~/.codex/{sessions,archived_sessions}.

Attribution: newer rollouts record why each turn started (turn_attribution.turn_trigger).
That is the only tool here with explicit human/automation metadata, so those messages are grade A.
Older rollouts have no trigger; they fall back to session-level signals (grade C).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import sqlite3

from ..model import Collector, SourceInfo
from ..util import glob_files, parse_iso, read_lines
from .base import Adapter, Progress, env_path, warn

HUMAN_TRIGGERS = {"composer", "queue", "edit_user_message", "remote_ios", "artifact_comment"}
AUTOMATION_TRIGGERS = {
    "automation_heartbeat_scheduled", "goal", "app_tool_send_message", "app_tool_create_thread",
    "resume_interrupted_task", "app_update_resume", "capacity_retry_manual",
}
_PAYLOAD_TYPE = re.compile(r'"payload":\s*\{\s*"type":\s*"(\w+)"')
_TOP_META = re.compile(r'^\{[^{]{0,160}"type":\s*"session_meta"')
_TS = re.compile(r'^\{"timestamp":\s*"([^"]+)"')
# payload types worth a full JSON parse; everything else (huge tool outputs) is skipped cheaply
_NEEDED = {"session_meta", "task_started", "item_completed", "function_call", "custom_tool_call", "turn_aborted", "user_message"}


def _text(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    for c in content or []:
        if isinstance(c, dict) and isinstance(c.get("text"), str):
            out.append(c["text"])
    return "\n".join(out)


class CodexAdapter(Adapter):
    id = "codex"
    label = "Codex"
    attribution = "explicit (turn_trigger) in recent logs, heuristic in older ones"

    def roots(self) -> List[Path]:
        base = env_path("CODEX_HOME") or (self.home / ".codex")
        return [base / "sessions", base / "archived_sessions"]

    def _files(self) -> List[Path]:
        s, a = self.roots()
        files = glob_files(s, "**/rollout-*.jsonl") + glob_files(a, "rollout-*.jsonl*")
        # file names start with the creation time: oldest first, so forks credit the original session
        return sorted(files, key=lambda p: p.name)

    def scan(self, col: Collector, progress: Optional[Progress] = None) -> None:
        files = self._files()
        self.seen_ids = set()
        for i, f in enumerate(files):
            if progress and i % 100 == 0:
                progress(f"codex {i}/{len(files)}")
            try:
                self._scan_file(col, f)
            except RuntimeError as e:
                col.warnings.append(f"codex: skipped {f.name}: {e}")
            except OSError as e:
                col.warnings.append(f"codex: cannot read {f.name}: {e}")
        n_db = self._scan_history_db(col)
        note = "turn_trigger attribution; archived .zst rollouts included"
        if n_db:
            note += f"; {n_db} threads that only exist in thread_history_1.sqlite"
        col.sources.append(SourceInfo(self.id, self.label, len(files), note))

    def _scan_file(self, col: Collector, f: Path) -> None:
        sid = f.name.split(".jsonl")[0].rsplit("-", 5)[-5:]
        sid = "-".join(sid) if len(sid) == 5 else f.stem
        ctx = None
        meta: Dict = {}
        turn_trigger: Dict[str, Optional[str]] = {}
        opened = False
        saw_item_user = False

        for line in read_lines(f):
            if _TOP_META.match(line):
                ptype = "session_meta"
            else:
                m = _PAYLOAD_TYPE.search(line[:400])
                if not m or m.group(1) not in _NEEDED:
                    continue
                ptype = m.group(1)
            try:
                o = json.loads(line)
            except ValueError:
                continue
            p = o.get("payload") or {}
            try:
                ts = parse_iso(o["timestamp"])
            except Exception:
                tm = _TS.match(line)
                if not tm:
                    continue
                ts = parse_iso(tm.group(1))

            if ptype == "session_meta":
                meta = p
                sid = p.get("id") or sid
                self.seen_ids.add(sid)
                excl = self._session_exclusion(p)
                ctx = col.session(self.id, sid, cwd=p.get("cwd"), exclude=excl)
                opened = True
                if ctx is None:
                    return
                continue
            if not opened:
                ctx = col.session(self.id, sid, cwd=None)
                opened = True
                if ctx is None:
                    return
            assert ctx is not None

            if ptype == "task_started":
                trig = (p.get("turn_attribution") or {}).get("turn_trigger")
                turn_trigger[p.get("turn_id", "")] = trig
            elif ptype == "item_completed":
                item = p.get("item") or {}
                it = item.get("type")
                if it == "UserMessage":
                    saw_item_user = True
                    self._user(col, ctx, ts, _text(item.get("content")), turn_trigger.get(p.get("turn_id", "")), meta)
                elif it == "AgentMessage":
                    ctx.event(ts, "agent")
            elif ptype in ("function_call", "custom_tool_call"):
                ctx.event(ts, "tool")
            elif ptype == "turn_aborted":
                ctx.event(ts, "interrupt" if p.get("reason") == "interrupted" else "agent")
            elif ptype == "user_message":
                # legacy event stream (no item_completed): only used when the modern item is absent
                if not turn_trigger and not saw_item_user:
                    self._user(col, ctx, ts, p.get("message") if isinstance(p.get("message"), str) else "", None, meta)
        if ctx is not None:
            ctx.close()

    @staticmethod
    def _session_exclusion(p: Dict) -> Optional[str]:
        src = p.get("source")
        if isinstance(src, dict) and "subagent" in src:
            return "subagent"
        if src == "exec":
            return "non_interactive_exec"
        if p.get("thread_source") == "subagent":
            return "subagent"
        return None

    @staticmethod
    def _user(col: Collector, ctx, ts: float, text: str, trig: Optional[str], meta: Dict) -> None:
        if not text.strip():
            return
        if trig is None:
            # no attribution in this log: threads that an agent created are not trusted as human
            if meta.get("thread_source") == "agent_created_thread":
                ctx.skip("agent_created_no_trigger", ts)
            else:
                ctx.human(ts, text, "C")
        elif trig in HUMAN_TRIGGERS:
            ctx.human(ts, text, "A")
        elif trig in AUTOMATION_TRIGGERS:
            ctx.skip("trigger:" + trig, ts)
        else:
            ctx.skip("unknown_trigger", ts)
            warn_key = "codex-unknown-trigger:" + str(trig)
            if warn_key not in col.warnings:
                col.warnings.append(warn_key + " (not counted as human; add it to HUMAN_TRIGGERS if it is)")


    # ------------------------------------------------------------------ sqlite
    # The desktop app keeps a database of every thread (thread_history_1.sqlite). On a long-lived
    # install it holds many more threads than the rollout files still on disk (measured: 1423 vs 328),
    # so rollouts alone would undercount old activity by a large factor. Opened read-only.
    def _scan_history_db(self, col: Collector) -> int:
        base = (env_path("CODEX_HOME") or (self.home / ".codex"))
        hist = base / "thread_history_1.sqlite"
        if not hist.exists():
            return 0
        try:
            db = sqlite3.connect(f"file:{hist}?mode=ro", uri=True)
            rows = db.execute(
                "select thread_id, created_at_ms, item_type, item_json from thread_items "
                "where item_type in ('userMessage','agentMessage','commandExecution','mcpToolCall','fileChange','webSearch','collabAgentToolCall') "
                "order by thread_id, created_at_ms"
            )
        except sqlite3.Error as e:
            col.warnings.append(f"codex: cannot read thread_history_1.sqlite: {e}")
            return 0
        agent_threads, spawned, cwds = set(), set(), {}
        state = base / "state_5.sqlite"
        if state.exists():
            try:
                st = sqlite3.connect(f"file:{state}?mode=ro", uri=True)
                agent_threads = {r[0] for r in st.execute("select id from threads where thread_source in ('agent_created_thread','subagent')")}
                spawned = {r[0] for r in st.execute("select child_thread_id from thread_spawn_edges")}
                cwds = {r[0]: r[1] for r in st.execute("select id, cwd from threads")}
            except sqlite3.Error as e:
                col.warnings.append(f"codex: state_5.sqlite partly unreadable ({e}); agent-created threads may be counted")
        # first time the app began recording clientId on user messages: before it, only heuristics exist
        era_start = None
        try:
            r = db.execute("select min(created_at_ms) from thread_items where item_type='userMessage' and item_json like '%\"clientId\":\"%'").fetchone()
            era_start = r[0] / 1000.0 if r and r[0] else None
        except sqlite3.Error:
            pass

        cur_tid, ctx, n_threads = None, None, 0
        skip_thread = False
        for tid, ms, itype, js in rows:
            if tid != cur_tid:
                if ctx is not None:
                    ctx.close()
                cur_tid, ctx, skip_thread = tid, None, False
                if tid in self.seen_ids:
                    skip_thread = True
                    continue
                excl = "subagent" if (tid in spawned) else ("agent_created" if tid in agent_threads else None)
                ctx = col.session(self.id, tid, cwd=cwds.get(tid), exclude=excl)
                if ctx is None:
                    skip_thread = True
                    continue
                n_threads += 1
            if skip_thread or ctx is None:
                continue
            ts = ms / 1000.0
            if itype == "userMessage":
                try:
                    o = json.loads(js)
                except ValueError:
                    continue
                text = _text(o.get("content"))
                if not text.strip():
                    continue
                has_cid = o.get("clientId") is not None
                if era_start is not None and ts >= era_start:
                    if has_cid:
                        ctx.human(ts, text, "B")
                    else:
                        ctx.skip("no_client_id", ts)
                else:
                    ctx.human(ts, text, "C")
            elif itype == "agentMessage":
                ctx.event(ts, "agent")
            else:
                ctx.event(ts, "tool")
        if ctx is not None:
            ctx.close()
        return n_threads
