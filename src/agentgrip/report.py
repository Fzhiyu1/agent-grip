"""Render the metrics dict into one self-contained HTML file (inline CSS and SVG, no network)."""
from __future__ import annotations

import datetime as dt
from html import escape
from typing import Any, Dict, List

from . import __version__, charts
from .i18n import BAND_ZH, EVIDENCE_ZH, PROFILE_TEXT, UI

CSS = """
:root{--bg:#faf9f7;--fg:#1f2328;--mut:#6b7280;--card:#fff;--line:#e5e2dc;--acc:#d97757}
@media (prefers-color-scheme:dark){:root{--bg:#16181c;--fg:#e6e6e6;--mut:#9aa1ab;--card:#1e2126;--line:#2e3239}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:38px 0 10px;padding-top:8px;border-top:1px solid var(--line)}h3{font-size:14px;margin:18px 0 6px;color:var(--mut);font-weight:600}
.sub{color:var(--mut);margin:0 0 14px}.pill{display:inline-block;padding:1px 9px;border:1px solid var(--line);border-radius:99px;margin:0 6px 4px 0;font-size:12.5px;color:var(--mut)}
.kpis{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0 4px}.kpi{flex:1 1 130px;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 14px}
.kpi b{display:block;font-size:24px;line-height:1.2}.kpi span{color:var(--mut);font-size:12.5px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(172px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}.card .n{font-size:12.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.card .v{font-size:28px;font-weight:650;line-height:1.15}.card .r{font-weight:600;color:var(--acc);margin:2px 0}.card .u,.card .d{font-size:12.5px;color:var(--mut)}
.note{color:var(--mut);font-size:13px}.chart{width:100%;height:auto;display:block}.chart.small{max-width:420px}
.grid{stroke:var(--line);stroke-width:1}.ref{stroke:var(--mut);stroke-dasharray:4 4;stroke-width:1}.tick{fill:var(--mut);font-size:11px}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12.5px;color:var(--mut);margin:4px 0}.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:22px}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mut);font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
details{margin:10px 0;background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 14px}summary{cursor:pointer;color:var(--mut);font-size:13px}
details dl{margin:8px 0 2px;display:grid;grid-template-columns:100px 1fr;gap:4px 12px;font-size:13px}details dt{color:var(--mut)}details dd{margin:0}
.warn{background:#fff7e6;border:1px solid #f0d9a8;color:#7a5b00;padding:8px 12px;border-radius:8px;font-size:13px;margin:8px 0}
@media (max-width:560px){main{padding:18px 12px 60px}h1{font-size:22px}details dl{grid-template-columns:1fr}.kpi b{font-size:20px}.card .v{font-size:24px}.two{grid-template-columns:1fr}}
@media (prefers-color-scheme:dark){.warn{background:#2b2412;border-color:#5a4a1a;color:#e6c97a}}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:6px 20px;font-size:13.5px}.stats div{display:flex;justify-content:space-between;border-bottom:1px dotted var(--line);padding:3px 0}.stats b{font-variant-numeric:tabular-nums}
footer{margin-top:40px;color:var(--mut);font-size:12.5px}
"""


def _pct(x: float) -> str:
    return "%.1f%%" % (x * 100)


def _num(x: Any) -> str:
    if isinstance(x, float):
        return ("%d" % x) if x.is_integer() else ("%.1f" % x)
    return "{:,}".format(x) if isinstance(x, int) else str(x)


def _legend(items) -> str:
    return '<div class="legend">' + "".join(f'<span><i style="background:{c}"></i>{escape(n)}</span>' for n, c in items) + "</div>"


class _R:
    def __init__(self, m: Dict[str, Any], lang: str):
        self.m, self.lang = m, lang
        self.t = UI[lang]

    def evidence(self, key: str, title: str = "") -> str:
        ev = self.m[key]["evidence"]
        if self.lang == "zh" and key in EVIDENCE_ZH:
            z = EVIDENCE_ZH[key]
            fill = dict(
                window=self.m["meta"]["window_min"],
                idle=self.m["meta"]["idle_gap_min"],
                tz=self.m["meta"]["tz"],
                day_start=self.m["meta"]["day_start_hour"],
            )
            meas, meth, lim = z["measures"], z["method"].format(**fill), z["limits"]
        else:
            meas, meth, lim = ev["measures"], ev["method"], ev["limits"]
        t = self.t
        return (
            f'<details><summary>{t["evidence"]}{(" · " + escape(title)) if title else ""}</summary><dl>'
            f'<dt>{t["measures"]}</dt><dd>{escape(meas)}</dd>'
            f'<dt>{t["method"]}</dt><dd>{escape(meth)}</dd>'
            f'<dt>{t["samples"]}</dt><dd>{_num(ev["n"])}</dd>'
            f'<dt>{t["limits"]}</dt><dd>{escape(lim)}</dd></dl></details>'
        )

    def kv(self, rows: List) -> str:
        return '<div class="stats">' + "".join(f"<div><span>{escape(k)}</span><b>{escape(str(v))}</b></div>" for k, v in rows) + "</div>"

    def band(self, s: str) -> str:
        return BAND_ZH.get(s, s) if self.lang == "zh" else s

    # ------------------------------------------------------------------
    def render(self) -> str:
        m, t = self.m, self.t
        head = f'<!doctype html><html lang="{self.lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{t["title"]}</title><style>{CSS}</style></head><body><main>'
        foot = f'<footer>agent-grip {__version__} · {t["generated"]} {dt.datetime.now().strftime("%Y-%m-%d %H:%M")} · {escape(m["meta"]["tz"])}</footer></main></body></html>'
        body = [f'<h1>{t["title"]}</h1><p class="sub">{t["subtitle"]}</p>']
        if m["empty"]:
            body.append(f'<div class="warn">{t["no_data"]}</div>')
            body.append(self.trust())
            return head + "".join(body) + foot
        ov = m["overview"]
        body.append(
            '<div class="kpis">'
            f'<div class="kpi"><b>{_num(ov["messages"])}</b><span>{t["messages"]}</span></div>'
            f'<div class="kpi"><b>{_num(ov["sessions"])}</b><span>{t["sessions"]}</span></div>'
            f'<div class="kpi"><b>{_num(ov["active_days"])}</b><span>{t["active_days"]}</span></div>'
            f'<div class="kpi"><b>{escape(ov["first"])}</b><span>{t["range"]} → {escape(ov["last"])}</span></div></div>'
        )
        body.append("".join(f'<span class="pill">{escape(k)} {_num(v)}</span>' for k, v in sorted(ov["by_tool"].items(), key=lambda x: -x[1])))
        for w in m["warnings"]:
            body.append(f'<div class="warn">{escape(w)}</div>')
        body += [self.profile(), self.volume(), self.concurrency(), self.sessions(), self.style(), self.delegation(), self.rhythm(), self.trust()]
        body.append(f'<h2>{t["how"]}</h2><p>{t["how_text"]}</p>')
        return head + "".join(body) + foot

    def profile(self) -> str:
        t = self.t
        cards = []
        for c in self.m["profile"]:
            name, unit, detail = PROFILE_TEXT[self.lang][c["key"]]
            band = self.band(c["band"]) if c["band"] else ""
            facts = dict(c["facts"])
            if facts.get("revisit") is not None:
                detail += (", median revisit gap {revisit} min" if self.lang == "en" else "，回访停顿中位 {revisit} 分钟")
            cards.append(
                f'<div class="card"><div class="n">{escape(name)}</div><div class="v">{_num(c["value"])}</div>'
                + (f'<div class="r">{escape(band)}</div>' if band else "")
                + f'<div class="u">{escape(unit.format(**facts))}</div><div class="d">{escape(detail.format(**facts))}</div></div>'
            )
        return f'<h2>{t["profile"]}</h2><div class="cards">{"".join(cards)}</div><p class="note">{t["profile_note"]}</p>'

    def volume(self) -> str:
        m, t = self.m, self.t
        days = m["concurrency"]["days"]
        mon = m["tools"]["monthly"]
        tools = sorted(m["overview"]["by_tool"], key=lambda k: -m["overview"]["by_tool"][k])
        months = list(mon)
        ch1 = charts.bars([d["day"][5:] for d in days], [(t["messages"], [d["msgs"] for d in days], "#2b6cb0")], max_x_labels=10, title=t["daily_msgs"])
        ch2 = charts.bars(months, [(tool, [mon[x].get(tool, 0) for x in months], charts.color_for(tool, i)) for i, tool in enumerate(tools)], title=t["monthly_tools"])
        leg = _legend([(k, charts.color_for(k, i)) for i, k in enumerate(tools)])
        return f'<h2>{t["volume"]}</h2><h3>{t["daily_msgs"]}</h3>{ch1}<h3>{t["monthly_tools"]}</h3>{leg}{ch2}{self.evidence("overview", t["volume"])}{self.evidence("tools", t["monthly_tools"])}'

    def concurrency(self) -> str:
        m, t = self.m, self.t
        c = m["concurrency"]
        days = c["days"]
        labels = [d["day"][5:] for d in days]
        ch = charts.lines(
            labels,
            [(t["peak_touched"], [d["peak_touched"] for d in days], "#a0aec0"), (t["peak_bf"], [d["peak_bf"] for d in days], "#c53030"), (t["median_bf"], [d["median_bf"] for d in days], "#2f855a")],
            ref=4,
            title=t["daily_conc"],
            area_first=True,
        )
        leg = _legend([(t["peak_touched"], "#a0aec0"), (t["peak_bf"], "#c53030"), (t["median_bf"], "#2f855a")])
        hb = c["hist_bf"]
        tot = sum(hb.values()) or 1
        hist = charts.hbars([(("%d+" % k if k >= 12 else str(k)), v / tot, "#c53030") for k, v in sorted((int(a), b) for a, b in hb.items())], fmt=_pct)
        mo = c["months"]
        mch = charts.bars([r["month"][2:] for r in mo], [("p50", [r["p50"] for r in mo], "#68d391"), ("p90", [r["p90"] for r in mo], "#ed8936"), ("max", [r["max"] for r in mo], "#e53e3e")], stacked=False, title=t["monthly_conc"])
        mleg = _legend([("p50", "#68d391"), ("p90", "#ed8936"), ("max", "#e53e3e")])
        bf, tc = c["back_and_forth"], c["touched"]
        kv = self.kv(
            [
                (t["median"] + " / p90 / max (back-and-forth)", f'{bf["p50"]} / {bf["p90"]} / {bf["max"]}'),
                (t["median"] + " / p90 / max (touched)", f'{tc["p50"]} / {tc["p90"]} / {tc["max"]}'),
                (t["switch"], _pct(c["switch_ratio"])),
                (t["multi_tool"], _pct(c["multi_tool_window_share"])),
            ]
        )
        inf = m["inflight"]
        ish = inf["share"]
        irow = charts.hbars([(k, v, "#6b46c1") for k, v in ish.items()], fmt=_pct)
        return (
            f'<h2>{t["concurrency"]}</h2>{kv}<h3>{t["daily_conc"]}</h3>{leg}{ch}'
            f'<div class="two"><div><h3>{t["hist"]}</h3>{hist}</div><div><h3>{t["monthly_conc"]}</h3>{mleg}{mch}</div></div>'
            f'{self.evidence("concurrency", t["concurrency"])}<h3>{t["inflight"]}</h3><p class="note">{t["inflight_note"]}</p>{irow}{self.evidence("inflight", t["inflight"])}'
        )

    def sessions(self) -> str:
        m, t = self.m, self.t
        s = m["sessions"]
        d = s["depth"]
        kv = self.kv(
            [
                (t["depth"] + " (" + t["median"] + " / p90 / max)", f'{d["p50"]} / {d["p90"]} / {d["max"]}'),
                (t["one_shot"], _pct(s["one_shot_share"])),
                (t["deep"], _pct(s["deep_share"])),
                (t["revisit"] + " (" + t["median"] + " / p90)", f'{s["revisit_gap_min"]["p50"]:.0f} / {s["revisit_gap_min"]["p90"]:.0f}'),
            ]
        )
        lr = s["leave_return"]
        rows = charts.hbars([((f'{r["concurrent"]}+' if r["concurrent"] >= 8 else str(r["concurrent"])), r["rate"], "#ed8936") for r in lr], fmt=_pct, vmax=1)
        tbl = (
            f'<div class=\"tw\"><table><tr><th>#</th><th class="n">{t["left"]}</th><th class="n">{t["returned"]}</th></tr>'
            + "".join(f'<tr><td>{r["concurrent"]}</td><td class="n">{_num(r["left"])}</td><td class="n">{_pct(r["rate"])}</td></tr>' for r in lr)
            + "</table></div>"
        )
        return f'<h2>{t["followthrough"]}</h2>{kv}<h3>{t["leave_return"]}</h3><div class="two"><div>{rows}</div><div>{tbl}</div></div>{self.evidence("sessions", t["followthrough"])}'

    def style(self) -> str:
        m, t = self.m, self.t
        st = m["style"]
        rows = []
        tools = ["all"] + list(st["by_tool"])
        head = "".join(f'<th class="n">{escape(x if x != "all" else "ALL")}</th>' for x in tools)

        def cell(x, f):
            d = st["all"] if x == "all" else st["by_tool"][x]
            return f'<td class="n">{f(d)}</td>' if d else '<td class="n">-</td>'

        spec = [
            (t["sess_n"].replace(t["sess_n"], t["messages"]), lambda d: _num(d["n"])),
            (t["chars"] + " " + t["median"], lambda d: _num(d["chars"]["p50"])),
            (t["chars"] + " p90", lambda d: _num(d["chars"]["p90"])),
            (t["short"], lambda d: _pct(d["short_le10"])),
            (t["long"], lambda d: _pct(d["long_ge300"])),
            (t["question"], lambda d: _pct(d["question"])),
            (t["correction"], lambda d: _pct(d["correction"])),
            (t["bare"], lambda d: _pct(d["bare"])),
            (t["codeish"], lambda d: _pct(d["codeish"])),
        ]
        for lab, f in spec:
            rows.append(f"<tr><td>{escape(lab)}</td>" + "".join(cell(x, f) for x in tools) + "</tr>")
        return f'<h2>{t["style"]}</h2><div class=\"tw\"><table><tr><th></th>{head}</tr>{"".join(rows)}</table></div>{self.evidence("style", t["style"])}'

    def delegation(self) -> str:
        m, t = self.m, self.t
        d = m["delegation"]
        rows = "".join(
            f'<tr><td>{escape(k)}</td><td class="n">{_num(v["sessions"])}</td><td class="n">{_num(v["human"])}</td><td class="n">{v["calls_per_msg"]}</td><td class="n">{_pct(v["interrupt_rate"])}</td></tr>'
            for k, v in sorted(d["by_tool"].items())
        )
        mo = d["months"]
        ch = charts.lines([r["month"][2:] for r in mo], [(t["calls"], [r["calls_per_msg"] for r in mo], "#6b46c1")], title=t["calls"]) if mo else ""
        return (
            f'<h2>{t["delegation"]}</h2><div class=\"tw\"><table><tr><th>{t["tool"]}</th><th class="n">{t["sess_n"]}</th><th class="n">{t["messages"]}</th><th class="n">{t["calls"]}</th><th class="n">{t["interrupt"]}</th></tr>{rows}</table></div>'
            f'<h3>{t["calls"]}</h3>{ch}{self.evidence("delegation", t["delegation"])}'
        )

    def rhythm(self) -> str:
        m, t = self.m, self.t
        r = m["rhythm"]
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] if self.lang == "en" else ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        heat = charts.heatmap(r["heat"], days)
        rows = [(t["late"], _pct(r["late_share_0_5"]))]
        n = r["night"]
        if n:
            f = lambda h: "%02d:%02d" % (int(h) % 24, int((h % 1) * 60))
            rows += [
                (t["nights"], n["nights"]),
                (t["last_msg"], f(n["last_msg_hour_p50"])),
                (t["first_msg"], f(n["first_msg_hour_p50"])),
                (t["silence"] + " (" + t["median"] + " / p90)", "%.1f h / %.1f h" % (n["silence_h"]["p50"], n["silence_h"]["p90"])),
                (t["under6"], _pct(n["under6h"])),
                (t["ge8"], _pct(n["ge8h"])),
            ]
        return f'<h2>{t["rhythm"]}</h2><h3>{t["heat"]}</h3>{heat}{charts.hour_bars(r["hours"])}<h3>{t["night"]}</h3>{self.kv(rows)}{self.evidence("rhythm", t["rhythm"])}'

    def trust(self) -> str:
        m, t = self.m, self.t
        g = m["quality"]["grades"]
        tot = sum(g.values()) or 1
        gt = m["meta"]["grade_text"]
        grows = "".join(f'<tr><td><b>{k}</b></td><td class="n">{_num(g.get(k, 0))}</td><td class="n">{_pct(g.get(k, 0) / tot)}</td><td>{escape(gt[k])}</td></tr>' for k in ("A", "B", "C"))
        keys = sorted({k for c in m["audit"].values() for k in c if k.startswith(("excluded:", "sessions_excluded:"))})
        tools = sorted(m["audit"])
        arows = "".join(
            f"<tr><td>{escape(k)}</td>" + "".join(f'<td class="n">{_num(m["audit"][x].get(k, 0)) if m["audit"][x].get(k, 0) else "·"}</td>' for x in tools) + "</tr>" for k in keys
        )
        kept = "<tr><td><b>" + t["kept"] + "</b></td>" + "".join(f'<td class="n"><b>{_num(m["audit"][x].get("human_kept", 0))}</b></td>' for x in tools) + "</tr>"
        src = "".join(f'<tr><td>{escape(s["label"])}</td><td class="n">{_num(s["files"])}</td><td>{escape(s["note"])}</td></tr>' for s in m["sources"])
        return (
            f'<h2>{t["trust"]}</h2><p>{t["trust_intro"]}</p>'
            f'<div class=\"tw\"><table><tr><th>{t["grade"]}</th><th class="n">{t["messages"]}</th><th class="n">%</th><th></th></tr>{grows}</table></div>'
            f'<div class=\"tw\"><table><tr><th></th>{"".join(f"<th class=n>{escape(x)}</th>" for x in tools)}</tr>{kept}{arows}</table></div>'
            f'<h3>{t["sources"]}</h3><div class=\"tw\"><table><tr><th>{t["tool"]}</th><th class="n">files</th><th></th></tr>{src}</table></div>'
        )


def render(metrics: Dict[str, Any], lang: str = "en") -> str:
    return _R(metrics, lang if lang in UI else "en").render()
