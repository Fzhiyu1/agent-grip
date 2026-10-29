from conftest import iso, jl

from agentgrip.adapters.claude import ClaudeAdapter
from agentgrip.adapters.pi import PiAdapter
from agentgrip.model import Collector


def user(sec, text, **kw):
    o = {"type": "user", "timestamp": iso(sec), "cwd": "/work/app", "message": {"role": "user", "content": text}}
    o.update(kw)
    return o


def test_claude_filters_tool_results_sidechains_meta_slash_and_injected(home):
    p = home / ".claude" / "projects" / "-work-app" / "sess-1.jsonl"
    jl(
        p,
        [
            user(0, "refactor the parser"),
            {"type": "assistant", "timestamp": iso(2), "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash"}, {"type": "tool_use", "name": "Read"}]}},
            user(3, [{"type": "tool_result", "content": "ok"}]),
            user(4, "sidechain prompt", isSidechain=True),
            user(5, "meta turn", isMeta=True),
            user(6, "/compact"),
            user(7, "<command-name>x</command-name>"),
            user(8, "[Request interrupted by user]"),
            user(60, "ok continue"),
        ],
    )
    col = Collector()
    ClaudeAdapter(home).scan(col)
    ds = col.finish()
    assert len(ds.msgs) == 2 and all(m.grade == "B" for m in ds.msgs)
    s = ds.sessions["claude:sess-1"]
    assert s.tool_calls == 2 and s.interrupts == 1
    a = ds.audit["claude"]
    assert a["excluded:meta"] == 1 and a["excluded:slash_command"] == 1 and a["excluded:injected"] == 1


def test_claude_sdk_sessions_are_excluded(home):
    jl(home / ".claude" / "projects" / "-w" / "s.jsonl", [user(0, "scripted run", entrypoint="sdk-cli")])
    col = Collector()
    ClaudeAdapter(home).scan(col)
    assert col.finish().msgs == []


def test_claude_history_backfills_only_sessions_without_a_transcript(home):
    jl(home / ".claude" / "projects" / "-w" / "has-transcript.jsonl", [user(0, "from transcript")])
    jl(
        home / ".claude" / "history.jsonl",
        [
            {"display": "from transcript", "timestamp": 1_790_000_000_000, "project": "/w", "sessionId": "has-transcript"},
            {"display": "old prompt one", "timestamp": 1_780_000_000_000, "project": "/w", "sessionId": "gone"},
            {"display": "/status", "timestamp": 1_780_000_100_000, "project": "/w", "sessionId": "gone"},
            {"display": "old prompt two", "timestamp": 1_780_000_900_000, "project": "/w", "sessionId": "gone"},
        ],
    )
    col = Collector()
    ClaudeAdapter(home).scan(col)
    ds = col.finish()
    per = {}
    for m in ds.msgs:
        per[m.session] = per.get(m.session, 0) + 1
    assert per == {"claude:has-transcript": 1, "claude:gone": 2}


def pi_msg(sec, role, content, **kw):
    m = {"role": role, "content": content, "timestamp": int((1_790_000_000 + sec) * 1000)}
    m.update(kw)
    return {"type": "message", "id": f"m{sec}", "timestamp": iso(sec), "message": m}


def pi_file(home, name, rows, cwd="/work/app"):
    jl(home / ".pi" / "agent" / "sessions" / "--work-app--" / name, [{"type": "session", "id": name.split("_", 1)[1][:-6], "timestamp": iso(0), "cwd": cwd}] + rows)


def test_pi_forked_copy_is_counted_once_and_orchestrator_prefix_dropped(home):
    rows = [pi_msg(1, "user", [{"type": "text", "text": "build the thing"}]), pi_msg(2, "assistant", [{"type": "toolCall"}], stopReason="toolUse")]
    pi_file(home, "2026-10-01T00-00-00-000Z_aaaa.jsonl", rows + [pi_msg(100, "user", [{"type": "text", "text": "Task: do X"}])])
    pi_file(home, "2026-10-01T00-05-00-000Z_bbbb.jsonl", rows)  # fork: same early history
    col = Collector()
    PiAdapter(home).scan(col)
    ds = col.finish()
    assert len(ds.msgs) == 1 and ds.msgs[0].grade == "C"
    a = ds.audit["pi"]
    assert a["excluded:forked_duplicate"] == 1 and a["excluded:orchestrator"] == 1
    assert ds.sessions["pi:aaaa"].tool_calls == 1


def test_pi_aborted_assistant_counts_as_interrupt(home):
    pi_file(home, "2026-10-01T00-00-00-000Z_cccc.jsonl", [pi_msg(1, "user", [{"type": "text", "text": "go"}]), pi_msg(2, "assistant", [], stopReason="aborted")])
    col = Collector()
    PiAdapter(home).scan(col)
    assert col.finish().sessions["pi:cccc"].interrupts == 1


def test_uniflo_bridge_skips_dedicated_tools_and_subagents(home, tmp_path, monkeypatch):
    import json
    import stat

    from agentgrip.adapters.uniflo import UnifloAdapter

    ls = [
        {"key": "dsh:1", "harness": "dsh", "id": "1", "cwd": "/w"},
        {"key": "dsh:2", "harness": "dsh", "id": "2", "cwd": "/w", "parent": "dsh:1"},
        {"key": "codex:9", "harness": "codex", "id": "9", "cwd": "/w"},
    ]
    ev = [
        {"event": {"kind": "user_message", "ts": 1_790_000_000_000, "text": "hello there"}},
        {"event": {"kind": "user_message", "ts": 1_790_000_100_000, "text": "injected", "synthetic": True}},
        {"event": {"kind": "tool_call", "ts": 1_790_000_101_000}},
    ]
    fake = tmp_path / "uniflo"
    fake.write_text(
        "#!/usr/bin/env python3\nimport sys,json\n"
        f"LS=json.loads({json.dumps(json.dumps(ls))})\nEV=json.loads({json.dumps(json.dumps(ev))})\n"
        "if sys.argv[1]=='ls': print(json.dumps(LS))\n"
        "else:\n    [print(json.dumps(e)) for e in EV]\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(tmp_path) + ":" + __import__("os").environ["PATH"])
    col = Collector()
    UnifloAdapter(home).scan(col)
    ds = col.finish()
    assert [m.tool for m in ds.msgs] == ["dsh"] and ds.msgs[0].grade == "C"
    assert ds.audit["dsh"]["excluded:synthetic"] == 1
    assert ds.sessions["dsh:1"].tool_calls == 1
