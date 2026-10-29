"""Synthetic fixtures only. Never copy real session content into tests."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def jl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def iso(sec: float) -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(1_790_000_000 + sec, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@pytest.fixture
def home(tmp_path):
    return tmp_path
