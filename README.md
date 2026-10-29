# agent-grip

Measure how you drive AI coding agents, from your own session logs.
One command, one offline HTML report. Nothing is uploaded; log files are only read.

```sh
pipx install git+https://github.com/Fzhiyu1/agent-grip   # or: pip install .
agent-grip --open
```

Python 3.9+, standard library only. Reads Codex, Claude Code, Pi and oh-my-pi directly, and about 30 more tools (Gemini CLI, OpenCode, Cursor, Cline, ...) through [uniflo](https://github.com/Crosery/uniflo) when it is on your `PATH`.

## What the report shows

| Section | Question it answers |
|---|---|
| Profile | Five cards: parallelism, delegation, steering, follow-through, cadence |
| Volume and tool handover | How much you send, and which tool you were using when |
| Concurrency | How many sessions you drive at once, daily peak vs. typical, by month |
| Sessions in flight | How many sessions are running at once, counting agent work |
| Sessions and returns | How deep sessions go, and whether you come back after leaving |
| Instruction style | Length, questions, corrections, bare "ok", pasted paths |
| Delegation | Tool calls per message you send; how often you interrupt |
| Rhythm | Hours of the day, weekday heat map, longest overnight pause |
| Trust and audit | What each adapter kept and threw away, and the evidence grade of every message |

Every block has an **Evidence** drawer: what it measures, how it is computed, the sample size, and what it cannot tell you.

## Why you can trust the numbers (and where not to)

- **Human vs. automation is the hard part.** Logs mix your messages with tool results, subagent prompts, heartbeats and injected context. Each adapter removes those and grades what is left:
  - `A` explicit metadata says a human sent it (Codex `turn_trigger`)
  - `B` structural signal (Claude Code sidechain/meta/tool_result removed; Codex client id)
  - `C` heuristic only (Pi, uniflo bridge, old Codex logs)
- The **Audit** table lists every exclusion with a count, so a filter that is too aggressive or too lax is visible.
- Two traps found on real data and handled: Pi **forks copy history into new files** (the same message appears in several), and Codex keeps **more threads in a SQLite database than rollout files on disk** (measured 1423 vs 328).
- Message text is read once, reduced to booleans and lengths, then dropped. Neither the HTML nor `--json` contains message text.
- Bands in the profile cards are rules of thumb in `metrics.BANDS`. There is no population baseline in local logs, so this tool **cannot tell you how you rank against other people**.
- It counts behaviour, not outcomes. A pause in messages is not sleep; more parallel sessions is not automatically better.

## Options

```text
-o, --out PATH         HTML report path (default agent-grip-report.html)
    --json PATH        also write raw metrics (counts only)
    --tools a,b        limit to some adapters; --list-tools shows what is found
    --home DIR         read logs from another home directory (e.g. a backup)
    --since 30d|DATE   only count recent messages
    --tz Asia/Shanghai time zone for days and hours (default: local)
    --lang en|zh       report language (default: from locale)
    --window MIN       concurrency window, default 30
    --idle-gap MIN     in-flight session ends after this much silence, default 10
    --day-start HOUR   late nights belong to the previous day, default 5
    --exclude-pattern REGEX   drop your own bot/dispatcher prompts (repeatable)
    --include-temp     keep sessions run from temp directories
```

## Add a tool

Subclass `Adapter` in `src/agentgrip/adapters/`, implement `roots()` and `scan()`, and register it in `adapters/__init__.py`. Inside `scan()` you only call four things on the collector (`session`, `human`, `skip`, `event`); span tracking, merging of paste bursts, the audit table and the evidence grades come for free. See `adapters/base.py` and `docs/adapters.md`. Adapters must never write to a tool's data directory; the tests assert that.

## Privacy

Runs offline, writes only the two output files you ask for, imports nothing outside the standard library, and the report has no scripts, fonts or network references (a test checks this). Reports describe your own work habits, so `agent-grip-report*` is git-ignored by default; review before sharing one.

## Develop

```sh
pip install -e . pytest && pytest
```

Test fixtures are synthetic on purpose. Do not copy real sessions into `tests/`.

MIT licensed.
