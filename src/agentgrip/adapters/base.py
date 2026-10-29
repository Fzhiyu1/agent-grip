"""Adapter contract.

An adapter knows where one AI tool keeps its session logs and how to tell a human-typed message
from everything else. It must never write to the log directories and never keep message text.

To add a tool: subclass Adapter, set `id`/`label`, implement `roots()` and `scan()`, then add the
class to REGISTRY in adapters/__init__.py. Use these Collector calls inside scan():

    ctx = col.session(tool, session_id, cwd=cwd, exclude=None)   # None means excluded
    ctx.human(ts, text, grade)    # candidate user message; grade is "A", "B" or "C"
    ctx.skip(reason, ts)          # user-role message that is not human
    ctx.event(ts, kind)           # kind: "tool", "agent" or "interrupt"
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, List, Optional

from ..model import Collector

Progress = Callable[[str], None]


class Adapter:
    id = ""
    label = ""
    # how trustworthy "this user message was typed by a human" is for this tool's logs
    attribution = "heuristic"

    def __init__(self, home: Optional[Path] = None):
        self.home = Path(home) if home else Path.home()

    def roots(self) -> List[Path]:
        """Directories this adapter will read. Used for detection and shown in the report."""
        raise NotImplementedError

    def detect(self) -> bool:
        return any(r.exists() for r in self.roots())

    def scan(self, col: Collector, progress: Optional[Progress] = None) -> None:
        raise NotImplementedError


def env_path(name: str) -> Optional[Path]:
    v = os.environ.get(name)
    return Path(v).expanduser() if v else None


def warn(msg: str) -> None:
    print("warning: " + msg, file=sys.stderr)
