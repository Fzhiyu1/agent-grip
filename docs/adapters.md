# Writing an adapter

An adapter answers one question: **which user-role entries in this tool's logs did a human type?**

## Contract

```python
class MyAdapter(Adapter):
    id = "mytool"            # shown in the report, used by --tools
    label = "My Tool"
    attribution = "..."      # one line: how trustworthy "human" is for this tool

    def roots(self) -> list[Path]: ...        # directories read; used by detection and --list-tools
    def scan(self, col: Collector, progress=None) -> None: ...
```

Inside `scan()`:

```python
ctx = col.session("mytool", session_id, cwd=cwd)   # None -> excluded (temp dir etc.), just return
ctx.human(ts, text, "B")     # candidate human message, grade A, B or C
ctx.skip("injected", ts)     # user-role entry that is NOT human; the reason lands in the Audit table
ctx.event(ts, "tool")        # also "agent" and "interrupt"; keeps the in-flight span alive
ctx.close()
```

`ts` is epoch seconds. Feed events in time order within a session.

## Checklist (each item was a real bug in the first three adapters)

1. Look for explicit attribution first (a trigger, `isMeta`, `synthetic`). Grade A or B only if the log says so.
2. Remove tool results that come back as user-role entries.
3. Remove subagent sessions, SDK/exec runs and orchestrator dispatches.
4. Check for **duplicated history**: forks, resumed sessions and compaction can repeat messages across files.
5. Check whether the **log directory is the whole story**: clean-up jobs and databases may hold more than the files.
6. Do not rely on exact JSON spacing when pre-filtering lines with substrings; use a whitespace-tolerant regex.
7. Compare your message count with the tool's own history view on a real machine before trusting it.
8. Add a synthetic fixture test for every exclusion rule. Never commit real sessions.

## Using uniflo instead

If the tool is already supported by [uniflo](https://github.com/Crosery/uniflo), you do not need an adapter: `UnifloAdapter` reads it through `uniflo ls/tail --json`. Write a dedicated adapter only when the tool exposes better attribution than uniflo's `synthetic` flag.
