"""Command line entry: agent-grip [options]. One command, one offline HTML report."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional

from . import __version__, adapters
from .i18n import default_lang
from .metrics import compute
from .model import Collector
from .report import render
from .util import parse_iso


def _tz(name: Optional[str]):
    if not name or name == "local":
        z = dt.datetime.now().astimezone()
        return z.tzinfo, "local (UTC%+d)" % (z.utcoffset().total_seconds() // 3600)
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name), name
    except Exception:
        pass
    sign = 1
    s = name.upper().replace("UTC", "").replace("GMT", "")
    if s.startswith("-"):
        sign, s = -1, s[1:]
    elif s.startswith("+"):
        s = s[1:]
    try:
        h, _, m = s.partition(":")
        off = sign * (int(h) * 60 + (int(m) if m else 0))
        return dt.timezone(dt.timedelta(minutes=off)), name
    except ValueError:
        raise SystemExit(f"cannot understand --tz {name!r}; use an IANA name like Asia/Shanghai or an offset like +8")


def _since(v: Optional[str], tz) -> Optional[float]:
    if not v:
        return None
    try:
        if v.endswith("d") and v[:-1].isdigit():
            return dt.datetime.now().timestamp() - int(v[:-1]) * 86400
        d = dt.datetime.fromisoformat(v)
        return (d.replace(tzinfo=tz) if d.tzinfo is None else d).timestamp()
    except ValueError:
        raise SystemExit(f"cannot understand --since {v!r}; use 30d or 2026-09-01")


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent-grip",
        description="Measure how you drive AI coding agents from your local session logs. Writes one offline HTML report. Nothing is uploaded; session logs are only read.",
    )
    p.add_argument("-o", "--out", default="agent-grip-report.html", help="HTML report path (default: %(default)s)")
    p.add_argument("--json", metavar="PATH", help="also write the raw metrics as JSON (counts only, no message text)")
    p.add_argument("--tools", help="comma-separated tool ids (default: every tool found). Available: " + ", ".join(sorted(adapters.REGISTRY)))
    p.add_argument("--home", help="read session logs from this home directory instead of ~")
    p.add_argument("--since", help="only count messages since this date (2026-09-01) or relative (30d)")
    p.add_argument("--tz", default="local", help="time zone for days and hours: IANA name or +8 offset (default: local)")
    p.add_argument("--lang", choices=["en", "zh"], default=None, help="report language (default: from the system locale)")
    p.add_argument("--window", type=_positive_int, default=30, metavar="MIN", help="concurrency window in minutes (default: %(default)s)")
    p.add_argument("--idle-gap", type=int, default=10, metavar="MIN", help="a session counts as in flight until this many idle minutes pass (default: %(default)s)")
    p.add_argument("--day-start", type=int, default=5, metavar="HOUR", help="hour at which a new day starts, so late nights count as the previous day (default: %(default)s)")
    p.add_argument("--include-temp", action="store_true", help="include sessions whose working directory is a temp dir (excluded by default)")
    p.add_argument("--exclude-pattern", action="append", default=[], metavar="REGEX", help="drop user messages matching this regex; repeatable. Use it to remove your own bot or dispatcher prompts")
    p.add_argument("--list-tools", action="store_true", help="show which tools are found on this machine and exit")
    p.add_argument("--open", action="store_true", help="open the report in the default browser when done")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("--version", action="version", version="agent-grip " + __version__)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    a = build_parser().parse_args(argv)
    home = Path(a.home).expanduser() if a.home else None
    log = (lambda s: None) if a.quiet else (lambda s: print(s, file=sys.stderr))

    if a.list_tools:
        for cls in adapters.REGISTRY.values():
            ad = cls(home)
            print(f"{ad.id:8} {'found' if ad.detect() else 'absent':7} {', '.join(str(r) for r in ad.roots())}")
        return 0

    try:
        chosen = adapters.build([t.strip() for t in a.tools.split(",") if t.strip()] if a.tools else None, home)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        return 2
    if not chosen:
        log("No supported AI tool logs found. Run with --list-tools to see where each tool is looked up, or use --home.")

    tz, tz_name = _tz(a.tz)
    col = Collector(
        idle_gap=a.idle_gap * 60.0,
        exclude_temp=not a.include_temp,
        extra_exclude=a.exclude_pattern,
        since=_since(a.since, tz),
    )
    for ad in chosen:
        log(f"reading {ad.label} ...")
        ad.scan(col, progress=None if a.quiet else (lambda s: print("\r" + s + "   ", end="", file=sys.stderr)))
        if not a.quiet:
            print("\r" + " " * 40 + "\r", end="", file=sys.stderr)
    ds = col.finish()
    metrics = compute(ds, tz, tz_name, window_min=a.window, day_start=a.day_start)
    lang = a.lang or default_lang()

    out = Path(a.out).expanduser()
    out.write_text(render(metrics, lang), encoding="utf-8")
    if a.json:
        Path(a.json).expanduser().write_text(json.dumps(metrics, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if metrics["empty"]:
        log("No human messages found; wrote an empty report.")
        return 1
    ov = metrics["overview"]
    log(f"{ov['messages']:,} human messages, {ov['sessions']:,} sessions, {ov['active_days']} active days -> {out}")
    if a.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
