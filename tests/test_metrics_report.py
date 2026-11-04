import datetime as dt
import json

from agentgrip.cli import main
from agentgrip.metrics import compute, sliding
from agentgrip.model import Collector
from agentgrip.report import render
from agentgrip.textclean import features, strip_context

UTC = dt.timezone.utc


def test_sliding_window_counts_touched_and_back_and_forth():
    t, b = sliding([0, 5, 6, 100], ["a", "b", "a", "c"], 10)
    assert t == [2, 2, 1, 1]
    assert b == [1, 0, 0, 0]  # only session "a" has two messages inside [0,10)


def test_sliding_rejects_non_positive_width():
    import pytest

    for w in (0, -5):
        with pytest.raises(ValueError):
            sliding([1.0, 2.0, 3.0], ["a", "a", "b"], w)


def test_cli_rejects_non_positive_window(capsys):
    import pytest

    for w in ("0", "-3"):
        with pytest.raises(SystemExit) as e:
            main(["--window", w])
        assert e.value.code == 2
        assert "must be >= 1" in capsys.readouterr().err


def test_sliding_window_matches_brute_force():
    import random

    random.seed(7)
    ts = sorted(random.uniform(0, 500) for _ in range(300))
    sids = [random.choice("abcdef") for _ in ts]
    t, b = sliding(ts, sids, 30)
    for i in range(len(ts)):
        inside = [sids[j] for j in range(len(ts)) if ts[i] <= ts[j] < ts[i] + 30]
        assert t[i] == len(set(inside))
        assert b[i] == sum(1 for s in set(inside) if inside.count(s) >= 2)


def test_features_and_context_stripping():
    f = features("为什么不行？")
    assert f.question and f.correction is True
    assert features("ok").bare and features("继续").bare and not features("ok but also rename it").bare
    assert features("see /Users/x/app.py").codeish
    wrapped = "<system-reminder>noise</system-reminder>real words"
    assert strip_context(wrapped) == "real words"
    assert strip_context("# Files mentioned by the user:\n\n## a.png\n\n## My request:\nhello") == "hello"


def _dataset(n_sessions=3, per=6):
    col = Collector()
    base = 1_790_000_000
    for s in range(n_sessions):
        ctx = col.session("codex", f"s{s}")
        for i in range(per):
            ts = base + s * 7 + i * 60
            ctx.human(ts, "please do thing number %d" % i, "A")
            ctx.event(ts + 5, "tool")
            ctx.event(ts + 6, "tool")
        ctx.close()
    return col.finish()


def test_compute_produces_evidence_for_every_block_and_no_text():
    m = compute(_dataset(), UTC, "UTC")
    for k in ("overview", "concurrency", "sessions", "style", "delegation", "inflight", "rhythm", "tools"):
        ev = m[k]["evidence"]
        assert ev["measures"] and ev["method"] and ev["limits"] and ev["n"]
    blob = json.dumps(m)
    assert "please do thing" not in blob  # message text must never reach the output
    assert m["delegation"]["calls_per_msg"] == 2.0


def test_empty_dataset_renders_without_crashing():
    m = compute(Collector().finish(), UTC, "UTC")
    html = render(m, "en")
    assert "No human messages" in html


def test_report_is_offline_and_both_languages_render():
    m = compute(_dataset(), UTC, "UTC")
    for lang in ("en", "zh"):
        h = render(m, lang)
        assert "<script" not in h and "http://" not in h and "https://" not in h and "src=" not in h
        assert "Agent Grip" in h


def test_cli_end_to_end_on_synthetic_home(home, tmp_path):
    from conftest import iso, jl

    jl(
        home / ".claude" / "projects" / "-w" / "s1.jsonl",
        [{"type": "user", "timestamp": iso(i * 90), "cwd": "/w", "message": {"role": "user", "content": f"task {i}"}} for i in range(5)],
    )
    out, js = tmp_path / "r.html", tmp_path / "r.json"
    rc = main(["--home", str(home), "-o", str(out), "--json", str(js), "--tz", "+0", "--lang", "en", "-q"])
    assert rc == 0 and out.exists()
    data = json.loads(js.read_text())
    assert data["overview"]["messages"] == 5
    assert main(["--home", str(home), "--tools", "nope", "-q"]) == 2
