"""Adapter registry. Add a new tool by writing an Adapter subclass and listing it here."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Type

from .base import Adapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .pi import OmpAdapter, PiAdapter
from .uniflo import UnifloAdapter

REGISTRY: Dict[str, Type[Adapter]] = {
    a.id: a for a in (CodexAdapter, ClaudeAdapter, PiAdapter, OmpAdapter, UnifloAdapter)
}


def build(ids: Optional[Sequence[str]] = None, home=None) -> List[Adapter]:
    """Instantiate adapters. ids=None means every adapter whose data directory exists."""
    if ids:
        unknown = [i for i in ids if i not in REGISTRY]
        if unknown:
            raise KeyError("unknown tool(s): " + ", ".join(unknown) + "; available: " + ", ".join(sorted(REGISTRY)))
        return [REGISTRY[i](home) for i in ids]
    found = [cls(home) for cls in REGISTRY.values()]
    return [a for a in found if a.detect()]
