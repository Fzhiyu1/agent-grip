"""Metrics. Pure functions over a Dataset; the result is a JSON-serialisable dict.

Every metric block carries an `evidence` entry: what it measures, how it is computed, how many
samples it rests on, and what it cannot tell you. The report renders those next to the numbers.
"""
from __future__ import annotations

import datetime as dt
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from statistics import median
from typing import Any, Dict, List, Sequence, Tuple

from .model import GRADE_TEXT, Dataset
from .util import percentile

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Bands used in the profile cards. They are rules of thumb written down so they can be argued with,
# not percentiles of any population: no cross-user baseline exists in local logs.
BANDS = {
    "parallelism_p90": [(2, "single-threaded"), (4, "juggling"), (99, "dispatching")],
    "delegation": [(5, "hands-on"), (20, "delegating"), (10**9, "long autonomous runs")],
}


def dist(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"n": 0, "p50": 0, "p75": 0, "p90": 0, "p99": 0, "max": 0, "mean": 0}
    return {
        "n": len(values),
        "p50": percentile(values, 0.5),
        "p75": percentile(values, 0.75),
        "p90": percentile(values, 0.9),
        "p99": percentile(values, 0.99),
        "max": max(values),
        "mean": round(sum(values) / len(values), 2),
    }


def _ev(measures: str, method: str, n: Any, limits: str) -> Dict[str, Any]:
    return {"measures": measures, "method": method, "n": n, "limits": limits}


def sliding(ts: Sequence[float], sids: Sequence[str], width: float) -> Tuple[List[int], List[int]]:
    """For each message i, look at [ts[i], ts[i]+width): (distinct sessions touched, sessions with >=2 messages)."""
    n = len(ts)
    cnt: Dict[str, int] = {}
    touched = two = 0
    j = 0
    out_t: List[int] = []
    out_b: List[int] = []
    for i in range(n):
        while j < n and ts[j] < ts[i] + width:
            c = cnt.get(sids[j], 0)
            cnt[sids[j]] = c + 1
            if c == 0:
                touched += 1
            elif c == 1:
                two += 1
            j += 1
        out_t.append(touched)
        out_b.append(two)
        c = cnt[sids[i]]
        cnt[sids[i]] = c - 1
        if c == 1:
            touched -= 1
        elif c == 2:
            two -= 1
    return out_t, out_b


def _day(ts: float, tz: dt.tzinfo, day_start: int) -> str:
    return dt.datetime.fromtimestamp(ts - day_start * 3600, tz).strftime("%Y-%m-%d")


def _month(ts: float, tz: dt.tzinfo) -> str:
    return dt.datetime.fromtimestamp(ts, tz).strftime("%Y-%m")


def compute(ds: Dataset, tz: dt.tzinfo, tz_name: str, window_min: int = 30, day_start: int = 5) -> Dict[str, Any]:
    msgs = ds.msgs
    ts = [m.ts for m in msgs]
    sids = [m.session for m in msgs]
    n = len(msgs)
    out: Dict[str, Any] = {"meta": {}, "empty": n == 0}
    out["meta"] = {
        "tz": tz_name,
        "window_min": window_min,
        "idle_gap_min": round(ds.idle_gap / 60, 1),
        "day_start_hour": day_start,
        "grade_text": GRADE_TEXT,
        "bands": {k: [[a, b] for a, b in v] for k, v in BANDS.items()},
    }
    if n == 0:
        out["quality"] = {"grades": {}, "by_tool": {}}
        out["audit"] = {t: dict(c) for t, c in ds.audit.items()}
        out["sources"] = [s.__dict__ for s in ds.sources]
        out["warnings"] = ds.warnings
        return out

    # ---------------------------------------------------------------- overview
    days: Dict[str, List[int]] = defaultdict(list)
    for i, m in enumerate(msgs):
        days[_day(m.ts, tz, day_start)].append(i)
    sess_keys = {m.session for m in msgs}
    per_day_msgs = [len(v) for v in days.values()]
    first_d = dt.datetime.fromtimestamp(ts[0], tz).date()
    last_d = dt.datetime.fromtimestamp(ts[-1], tz).date()
    tool_counts = Counter(m.tool for m in msgs)
    out["overview"] = {
        "messages": n,
        "sessions": len(sess_keys),
        "active_days": len(days),
        "first": first_d.isoformat(),
        "last": last_d.isoformat(),
        "span_days": (last_d - first_d).days + 1,
        "msgs_per_active_day": dist(per_day_msgs),
        "by_tool": dict(tool_counts),
        "evidence": _ev(
            "Volume of human-typed messages.",
            "Messages kept by each adapter's human filter (see Audit). A day starts at %02d:00 local time, so late-night work belongs to the previous day." % day_start,
            n,
            "Counts what you typed, not what was accomplished.",
        ),
    }

    # -------------------------------------------------------------- quality
    grades = Counter(m.grade for m in msgs)
    by_tool_grade: Dict[str, Dict[str, int]] = defaultdict(dict)
    for m in msgs:
        by_tool_grade[m.tool][m.grade] = by_tool_grade[m.tool].get(m.grade, 0) + 1
    out["quality"] = {"grades": dict(grades), "by_tool": dict(by_tool_grade)}

    # ----------------------------------------------------------- concurrency
    W = window_min * 60
    touched, bf = sliding(ts, sids, W)
    day_rows = []
    switches_by_day: Counter = Counter()
    for i in range(1, n):
        if sids[i] != sids[i - 1]:
            switches_by_day[_day(ts[i], tz, day_start)] += 1
    for d in sorted(days):
        idx = days[d]
        day_rows.append(
            {
                "day": d,
                "msgs": len(idx),
                "sessions": len({sids[i] for i in idx}),
                "switches": switches_by_day.get(d, 0),
                "peak_touched": max(touched[i] for i in idx),
                "peak_bf": max(bf[i] for i in idx),
                "median_bf": median([bf[i] for i in idx]),
            }
        )
    months: Dict[str, List[int]] = defaultdict(list)
    for i, t in enumerate(ts):
        months[_month(t, tz)].append(i)
    month_rows = []
    for mo in sorted(months):
        idx = months[mo]
        b = [bf[i] for i in idx]
        month_rows.append({"month": mo, "n": len(idx), "p50": percentile(b, 0.5), "p90": percentile(b, 0.9), "max": max(b)})
    n_sw = sum(switches_by_day.values())
    tools_in_window = []
    for i in range(n):
        j = bisect_right(ts, ts[i] + W - 1e-9)
        tools_in_window.append(len({msgs[k].tool for k in range(i, j)}) if j - i < 400 else 1)
    multi_tool = sum(1 for x in tools_in_window if x >= 2) / n
    out["concurrency"] = {
        "window_min": window_min,
        "back_and_forth": dist(bf),
        "touched": dist(touched),
        "hist_bf": dict(sorted(Counter(min(x, 12) for x in bf).items())),
        "hist_touched": dict(sorted(Counter(min(x, 12) for x in touched).items())),
        "days": day_rows,
        "months": month_rows,
        "switches_total": n_sw,
        "switch_ratio": round(n_sw / max(1, n - 1), 3),
        "multi_tool_window_share": round(multi_tool, 3),
        "evidence": _ev(
            "How many sessions you drive at once.",
            "For every human message, look %d min ahead: 'back-and-forth' = sessions in which you sent 2 or more messages in that window; 'touched' = sessions with at least 1 message." % window_min,
            n,
            "Counts your messages, not what you were thinking about. Waiting on a long agent run while sending nothing is invisible here. Bursts of messages in one session less than 8 s apart are merged. A back-and-forth value of 0 is normal: it means every session in that window got exactly one message.",
        ),
    }

    # ---------------------------------------------------- sessions and returns
    by_sess: Dict[str, List[float]] = defaultdict(list)
    for m in msgs:
        by_sess[m.session].append(m.ts)
    depth = [len(v) for v in by_sess.values()]
    revisit = []
    for v in by_sess.values():
        for a, b in zip(v, v[1:]):
            if b - a >= 300:
                revisit.append((b - a) / 60.0)
    end_ts = ts[-1]
    leave_tab: Dict[int, List[int]] = defaultdict(lambda: [0, 0])
    for i in range(n - 1):
        if sids[i + 1] == sids[i] or ts[i] > end_ts - 86400 or len(by_sess[sids[i]]) < 2:
            continue
        lo = bisect_left(ts, ts[i] - W)
        k = min(len({sids[x] for x in range(lo, i + 1)}), 8)
        vs = by_sess[sids[i]]
        pos = bisect_right(vs, ts[i])
        back = pos < len(vs) and vs[pos] - ts[i] <= 86400
        leave_tab[k][0] += 1 if back else 0
        leave_tab[k][1] += 1
    out["sessions"] = {
        "depth": dist(depth),
        "one_shot_share": round(sum(1 for d in depth if d == 1) / len(depth), 3),
        "deep_share": round(sum(1 for d in depth if d >= 20) / len(depth), 3),
        "revisit_gap_min": dist(revisit),
        "leave_return": [
            {"concurrent": k, "left": v[1], "returned_24h": v[0], "rate": round(v[0] / v[1], 3) if v[1] else 0}
            for k, v in sorted(leave_tab.items())
        ],
        "evidence": _ev(
            "How deep each session goes and whether you come back to it.",
            "depth = human messages per session. revisit gap = pause of 5 min or more between two of your messages in the same session. leave/return: when you leave a session for another, did you message it again within 24 h, split by how many sessions you touched in the previous %d min." % window_min,
            len(depth),
            "One-shot sessions include legitimate one-off questions. 'Came back' does not prove you remembered where you were. Messages in the last 24 h of data are excluded from leave/return.",
        ),
    }

    # ------------------------------------------------------------------ style
    def style(sel):
        k = len(sel)
        if not k:
            return None
        ch = [m.feat.chars for m in sel]
        f = lambda pred: round(sum(1 for m in sel if pred(m.feat)) / k, 3)
        return {
            "n": k,
            "chars": dist(ch),
            "short_le10": round(sum(1 for c in ch if c <= 10) / k, 3),
            "long_ge300": round(sum(1 for c in ch if c >= 300) / k, 3),
            "question": f(lambda x: x.question),
            "correction": f(lambda x: x.correction),
            "bare": f(lambda x: x.bare),
            "codeish": f(lambda x: x.codeish),
        }

    out["style"] = {
        "all": style(msgs),
        "by_tool": {t: style([m for m in msgs if m.tool == t]) for t in sorted(tool_counts)},
        "evidence": _ev(
            "How you phrase instructions: short or long, asking or telling, correcting, rubber-stamping.",
            "Regex features computed on message text with injected context blocks removed; only the resulting booleans and lengths are kept. 'bare' = a lone go-ahead like ok/continue. 'correction' = explicit negation or rollback wording. 'codeish' = contains a path, URL, code fence or file extension.",
            n,
            "Keyword rules are tuned for Chinese and English only and over- or under-count in other languages. Length is in characters, so Chinese and English are not directly comparable.",
        ),
    }

    # -------------------------------------------------------------- delegation
    deleg: Dict[str, Dict[str, float]] = {}
    tot_h = tot_t = tot_i = 0
    month_d: Dict[str, List[int]] = defaultdict(lambda: [0, 0, 0])
    for s in ds.sessions.values():
        if not (s.human and s.has_events):
            continue
        d = deleg.setdefault(s.tool, {"sessions": 0, "human": 0, "tool_calls": 0, "interrupts": 0})
        d["sessions"] += 1
        d["human"] += s.human
        d["tool_calls"] += s.tool_calls
        d["interrupts"] += s.interrupts
        tot_h += s.human
        tot_t += s.tool_calls
        tot_i += s.interrupts
        md = month_d[_month(s.first_ts, tz)]
        md[0] += s.human
        md[1] += s.tool_calls
        md[2] += s.interrupts
    for d in deleg.values():
        d["calls_per_msg"] = round(d["tool_calls"] / d["human"], 2) if d["human"] else 0
        d["interrupt_rate"] = round(d["interrupts"] / d["human"], 3) if d["human"] else 0
    out["delegation"] = {
        "by_tool": deleg,
        "calls_per_msg": round(tot_t / tot_h, 2) if tot_h else 0,
        "interrupt_rate": round(tot_i / tot_h, 3) if tot_h else 0,
        "months": [
            {"month": m, "calls_per_msg": round(v[1] / v[0], 2) if v[0] else 0, "interrupt_rate": round(v[2] / v[0], 3) if v[0] else 0, "human": v[0]}
            for m, v in sorted(month_d.items())
        ],
        "evidence": _ev(
            "How much the agent does per instruction you give, and how often you stop it.",
            "tool calls (shell, edits, searches, MCP) divided by human messages, over sessions that have a full transcript. Interrupts = times a turn was aborted by you.",
            tot_h,
            "Tool-call counts are not comparable across tools: each harness bundles actions differently (compare within a tool or across months). Sessions known only from prompt history have no transcript and are left out, so a tool whose old transcripts were cleaned up (often Claude Code) shows far fewer sessions here than in the volume charts.",
        ),
    }

    # ----------------------------------------------------- in-flight sessions
    edges: List[Tuple[float, int]] = []
    for s in ds.sessions.values():
        for a, b in s.spans:
            edges.append((a, 1))
            edges.append((b, -1))
    edges.sort()
    weight: Counter = Counter()
    cur = mx = 0
    last = None
    for t, d in edges:
        if last is not None and cur > 0 and t > last:
            weight[min(cur, 8)] += t - last
        cur += d
        last = t
        mx = max(mx, cur)
    tw = sum(weight.values())
    out["inflight"] = {
        "max": mx,
        "share": {str(k): round(v / tw, 3) for k, v in sorted(weight.items())} if tw else {},
        "active_hours": round(tw / 3600, 1),
        "evidence": _ev(
            "How many sessions are in flight at the same time, counting agent work, not only your typing.",
            "A session is in flight from one of your messages until %.0f min pass with no event of any kind. Time-weighted over all moments with at least one session in flight." % (ds.idle_gap / 60),
            len(ds.sessions),
            "A long silent command (no events for longer than the idle gap) ends the span early, so this under-counts rather than over-counts.",
        ),
    }

    # ----------------------------------------------------------------- rhythm
    heat = [[0] * 24 for _ in range(7)]
    hours = [0] * 24
    for t in ts:
        x = dt.datetime.fromtimestamp(t, tz)
        heat[x.weekday()][x.hour] += 1
        hours[x.hour] += 1
    late = sum(hours[0:5]) / n
    nights: Dict[str, Tuple[float, float, float, int]] = {}
    for a, b in zip(ts, ts[1:]):
        g = (b - a) / 3600.0
        if g < 3:
            continue
        xa = dt.datetime.fromtimestamp(a, tz)
        h = xa.hour + xa.minute / 60.0
        if not (h >= 20 or h < 6):
            continue
        key = (xa - dt.timedelta(hours=12)).strftime("%Y-%m-%d")
        if key not in nights or g > nights[key][2]:
            xb = dt.datetime.fromtimestamp(b, tz)
            nights[key] = (h + (24 if h < 12 else 0), xb.hour + xb.minute / 60.0, g, xa.weekday())
    rows = list(nights.values())
    rhythm_night = None
    if len(rows) >= 14:
        gaps = [r[2] for r in rows]
        rhythm_night = {
            "nights": len(rows),
            "last_msg_hour_p50": round(median([r[0] for r in rows]) % 24, 2),
            "first_msg_hour_p50": round(median([r[1] for r in rows]), 2),
            "silence_h": dist(gaps),
            "under6h": round(sum(1 for g in gaps if g < 6) / len(gaps), 3),
            "ge8h": round(sum(1 for g in gaps if g >= 8) / len(gaps), 3),
        }
    out["rhythm"] = {
        "heat": heat,
        "hours": hours,
        "late_share_0_5": round(late, 3),
        "night": rhythm_night,
        "evidence": _ev(
            "When you work, and the longest overnight pause in your messages.",
            "Clock hours of human messages in %s. Overnight pause = the longest gap of at least 3 h that starts between 20:00 and 06:00, one per night." % tz_name,
            n,
            "A pause in messages is NOT sleep. You may be away, asleep, or working somewhere that leaves no log. Treat it as an upper bound on rest, never a measurement of it.",
        ),
    }

    # -------------------------------------------------------------- tool mix
    tmonth: Dict[str, Counter] = defaultdict(Counter)
    for m in msgs:
        tmonth[_month(m.ts, tz)][m.tool] += 1
    out["tools"] = {
        "monthly": {mo: dict(c) for mo, c in sorted(tmonth.items())},
        "first_last": {
            t: [dt.datetime.fromtimestamp(min(x.ts for x in msgs if x.tool == t), tz).date().isoformat(), dt.datetime.fromtimestamp(max(x.ts for x in msgs if x.tool == t), tz).date().isoformat()]
            for t in tool_counts
        },
        "evidence": _ev(
            "Which tools you use and whether you use several at once or hand over between them.",
            "Messages per month per tool; multi-tool share = fraction of %d-min windows in which more than one tool received a message." % window_min,
            n,
            "Only tools with an adapter (and data on this machine) appear.",
        ),
    }

    out["profile"] = _profile(out)
    out["audit"] = {t: dict(c) for t, c in ds.audit.items()}
    out["sources"] = [s.__dict__ for s in ds.sources]
    out["warnings"] = ds.warnings
    return out


def _band(value: float, key: str) -> str:
    for limit, name in BANDS[key]:
        if value <= limit:
            return name
    return BANDS[key][-1][1]


def _profile(o: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Cards carry numbers plus a `key`; the report turns them into sentences in the chosen language."""
    c, s, st, d, ov = o["concurrency"], o["sessions"], o["style"]["all"], o["delegation"], o["overview"]
    return [
        {
            "key": "parallelism",
            "value": c["back_and_forth"]["p90"],
            "band": _band(c["back_and_forth"]["p90"], "parallelism_p90"),
            "facts": {"p50": c["back_and_forth"]["p50"], "max": c["back_and_forth"]["max"], "window": c["window_min"]},
        },
        {
            "key": "delegation",
            "value": d["calls_per_msg"],
            "band": _band(d["calls_per_msg"], "delegation") if d["calls_per_msg"] else "not measurable",
            "facts": {"interrupt": round(d["interrupt_rate"] * 100, 1)},
        },
        {
            "key": "steering",
            "value": round(st["correction"] * 100, 1),
            "band": "",
            "facts": {"bare": round(st["bare"] * 100, 1), "question": round(st["question"] * 100)},
        },
        {
            "key": "followthrough",
            "value": round((1 - s["one_shot_share"]) * 100, 1),
            "band": "",
            "facts": {
                "depth": s["depth"]["p50"],
                "deep": round(s["deep_share"] * 100),
                "revisit": round(s["revisit_gap_min"]["p50"]) if s["revisit_gap_min"]["n"] else None,
            },
        },
        {
            "key": "cadence",
            "value": round(ov["active_days"] / max(1, ov["span_days"]) * 100, 1),
            "band": "",
            "facts": {"days": ov["active_days"], "per_day": ov["msgs_per_active_day"]["p50"], "first": ov["first"], "last": ov["last"]},
        },
    ]
