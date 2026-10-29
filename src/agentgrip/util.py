"""Small helpers shared by adapters and metrics (stdlib only)."""
from __future__ import annotations

import datetime as _dt
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterator, List, Optional, Sequence


def parse_iso(s: str) -> float:
    """ISO-8601 timestamp (Z or offset, any fraction length) -> epoch seconds."""
    s = re.sub(r"Z$", "+00:00", s)
    m = re.match(r"^([^.]*)[.](\d+)(.*)$", s)
    if m:
        s = f"{m.group(1)}.{(m.group(2) + '000000')[:6]}{m.group(3)}"
    d = _dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.timestamp()


def percentile(values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile, p in [0,1]. Empty -> 0."""
    if not values:
        return 0
    v = sorted(values)
    return v[min(len(v) - 1, int(len(v) * p))]


def median(values: Sequence[float]) -> float:
    return percentile(values, 0.5)


def read_lines(path: Path) -> Iterator[str]:
    """Yield lines from .jsonl or .jsonl.zst."""
    if path.suffix != ".zst":
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                yield line
        return
    raw = path.read_bytes()
    data: Optional[bytes] = None
    try:  # python >= 3.14
        from compression import zstd as _z  # type: ignore

        data = _z.decompress(raw)
    except Exception:
        try:
            import zstandard  # type: ignore

            data = zstandard.ZstdDecompressor().decompressobj().decompress(raw)
        except Exception:
            exe = shutil.which("zstd")
            if exe:
                r = subprocess.run([exe, "-dc"], input=raw, capture_output=True)
                if r.returncode == 0:
                    data = r.stdout
    if data is None:
        raise RuntimeError("cannot decompress .zst (need python>=3.14, zstandard, or the zstd binary)")
    for line in data.decode("utf-8", errors="replace").splitlines(True):
        yield line


def day_key(ts: float, tz: _dt.tzinfo) -> str:
    return _dt.datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d")


def month_key(ts: float, tz: _dt.tzinfo) -> str:
    return _dt.datetime.fromtimestamp(ts, tz).strftime("%Y-%m")


def is_temp_path(p: Optional[str]) -> bool:
    """Working dirs under OS temp dirs are almost always scripts/tests, not real work."""
    if not p:
        return False
    p = p.replace("\\", "/")
    return (
        p.startswith(("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/"))
        or p in ("/tmp", "/private/tmp")
        or "/AppData/Local/Temp/" in p
    )


def glob_files(root: Path, pattern: str) -> List[Path]:
    return sorted(root.glob(pattern)) if root.exists() else []
