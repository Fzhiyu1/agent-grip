import json

from conftest import iso, jl

from agentgrip.adapters.codex import CodexAdapter
from agentgrip.model import Collector


def rollout(home, sid, rows, name=None):
    p = home / ".codex" / "sessions" / "2026" / "10" / "01" / (name or f"rollout-2026-10-01T00-00-00-{sid}.jsonl")
    jl(p, rows)


def meta(sid, **kw):
    pl = {"id": sid, "cwd": "/work/app", "source": "vscode", "thread_source": "user"}
    pl.update(kw)
    return {"timestamp": iso(0), "type": "session_meta", "payload": pl}


def turn(sec, tid, trigger):
    return {"timestamp": iso(sec), "type": "event_msg", "payload": {"type": "task_started", "turn_id": tid, "turn_attribution": {"turn_trigger": trigger}}}


def user(sec, tid, text):
    return {"timestamp": iso(sec), "type": "event_msg", "payload": {"type": "item_completed", "turn_id": tid, "item": {"type": "UserMessage", "id": "u" + str(sec), "content": [{"type": "text", "text": text}]}}}


def scan(home):
    col = Collector()
    CodexAdapter(home).scan(col)
    return col.finish()


SID = "11111111-1111-1111-1111-111111111111"


def test_trigger_separates_human_from_automation(home):
    rollout(home, SID, [meta(SID), turn(1, "t1", "composer"), user(1, "t1", "please fix the login bug"), turn(100, "t2", "automation_heartbeat_scheduled"), user(100, "t2", "heartbeat"), turn(200, "t3", "goal"), user(200, "t3", "continue goal")])
    ds = scan(home)
    assert [m.grade for m in ds.msgs] == ["A"]
    a = ds.audit["codex"]
    assert a["excluded:trigger:automation_heartbeat_scheduled"] == 1
    assert a["excluded:trigger:goal"] == 1


def test_subagent_and_exec_sessions_excluded(home):
    sub = "22222222-2222-2222-2222-222222222222"
    rollout(home, sub, [meta(sub, source={"subagent": {"thread_spawn": {"parent_thread_id": SID}}}), turn(1, "t", "composer"), user(1, "t", "child prompt")])
    ex = "33333333-3333-3333-3333-333333333333"
    rollout(home, ex, [meta(ex, source="exec"), turn(1, "t", "composer"), user(1, "t", "scripted")])
    ds = scan(home)
    assert ds.msgs == []
    assert ds.audit["codex"]["sessions_excluded:subagent"] == 1
    assert ds.audit["codex"]["sessions_excluded:non_interactive_exec"] == 1


def test_unknown_trigger_is_not_counted_and_is_reported(home):
    rollout(home, SID, [meta(SID), turn(1, "t1", "brand_new_trigger"), user(1, "t1", "hello")])
    ds = scan(home)
    assert ds.msgs == []
    assert any("brand_new_trigger" in w for w in ds.warnings)


def test_old_log_without_trigger_is_grade_c_but_agent_created_thread_is_dropped(home):
    rollout(home, SID, [meta(SID), {"timestamp": iso(1), "type": "event_msg", "payload": {"type": "task_started", "turn_id": "t1"}}, user(1, "t1", "old style prompt")])
    agent = "44444444-4444-4444-4444-444444444444"
    rollout(home, agent, [meta(agent, thread_source="agent_created_thread"), {"timestamp": iso(1), "type": "event_msg", "payload": {"type": "task_started", "turn_id": "t1"}}, user(1, "t1", "spawned by another agent")])
    ds = scan(home)
    assert [m.grade for m in ds.msgs] == ["C"]
    assert ds.audit["codex"]["excluded:agent_created_no_trigger"] == 1


def test_temp_dir_sessions_are_excluded_unless_asked(home):
    rollout(home, SID, [meta(SID, cwd="/private/var/folders/xx/T/scratch"), turn(1, "t", "composer"), user(1, "t", "hi there")])
    assert scan(home).msgs == []
    col = Collector(exclude_temp=False)
    CodexAdapter(home).scan(col)
    assert len(col.finish().msgs) == 1


def test_burst_of_messages_in_one_session_is_merged(home):
    rollout(home, SID, [meta(SID)] + [x for i in range(3) for x in (turn(i, f"t{i}", "composer"), user(i, f"t{i}", f"part {i}"))])
    ds = scan(home)
    assert len(ds.msgs) == 1
    assert ds.audit["codex"]["excluded:burst_merged"] == 2


def test_context_only_message_is_not_human(home):
    ctx = "<system-reminder>injected</system-reminder>"
    rollout(home, SID, [meta(SID), turn(1, "t", "composer"), user(1, "t", ctx)])
    ds = scan(home)
    assert ds.msgs == []
    assert ds.audit["codex"]["excluded:context_only"] == 1


def test_never_writes_to_the_log_directory(home):
    rollout(home, SID, [meta(SID), turn(1, "t", "composer"), user(1, "t", "hello")])
    before = sorted((p, p.stat().st_mtime_ns, p.stat().st_size) for p in (home / ".codex").rglob("*") if p.is_file())
    scan(home)
    after = sorted((p, p.stat().st_mtime_ns, p.stat().st_size) for p in (home / ".codex").rglob("*") if p.is_file())
    assert before == after
