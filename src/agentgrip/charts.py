"""Tiny dependency-free SVG chart helpers. Output is inlined in the report, no scripts, no fonts fetched."""
from __future__ import annotations

from html import escape
from typing import Dict, List, Optional, Sequence, Tuple

PALETTE = ["#d97757", "#6b46c1", "#2b6cb0", "#2f855a", "#b7791f", "#c53030", "#319795", "#718096"]
TOOL_COLORS = {"claude": "#d97757", "pi": "#6b46c1", "codex": "#2b6cb0", "omp": "#2f855a"}


def color_for(name: str, i: int = 0) -> str:
    return TOOL_COLORS.get(name, PALETTE[(i + 4) % len(PALETTE)])


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1
    import math

    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else ("%.1f" % v)


def _axis(w, h, ml, mb, mt, mr, ymax, ticks=4) -> str:
    out = []
    for i in range(ticks + 1):
        y = h - mb - (h - mb - mt) * i / ticks
        out.append(f'<line x1="{ml}" x2="{w - mr}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        out.append(f'<text x="{ml - 6}" y="{y + 4:.1f}" class="tick" text-anchor="end">{_fmt(ymax * i / ticks)}</text>')
    return "".join(out)


def bars(
    labels: Sequence[str],
    series: Sequence[Tuple[str, Sequence[float], str]],
    w: int = 760,
    h: int = 220,
    stacked: bool = True,
    max_x_labels: int = 12,
    title: str = "",
) -> str:
    """Vertical bars. series = [(name, values, color)]. Stacked or grouped."""
    n = len(labels)
    if n == 0:
        return ""
    ml, mr, mt, mb = 38, 8, 8, 24
    if stacked:
        tot = [sum(s[1][i] for s in series) for i in range(n)]
        ymax = _nice_max(max(tot))
    else:
        ymax = _nice_max(max(max(s[1]) for s in series))
    pw, ph = w - ml - mr, h - mt - mb
    slot = pw / n
    k = len(series)
    bw = max(1.0, slot * (0.86 if stacked else 0.86 / k))
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}" class="chart">', _axis(w, h, ml, mb, mt, mr, ymax)]
    for i in range(n):
        x0 = ml + slot * i + slot * 0.07
        base = 0.0
        for j, (name, vals, col) in enumerate(series):
            v = vals[i]
            if v <= 0:
                continue
            bh = ph * v / ymax
            if stacked:
                y = h - mb - ph * base / ymax - bh
                x = x0
            else:
                y = h - mb - bh
                x = x0 + bw * j
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{col}"><title>{escape(labels[i])} {escape(name)}: {_fmt(v)}</title></rect>')
            base += v
    step = max(1, -(-n // max_x_labels))
    for i in range(0, n, step):
        out.append(f'<text x="{ml + slot * (i + 0.5):.1f}" y="{h - 8}" class="tick" text-anchor="middle">{escape(labels[i])}</text>')
    out.append("</svg>")
    return "".join(out)


def lines(
    labels: Sequence[str],
    series: Sequence[Tuple[str, Sequence[float], str]],
    w: int = 760,
    h: int = 220,
    max_x_labels: int = 12,
    title: str = "",
    ref: Optional[float] = None,
    area_first: bool = False,
) -> str:
    n = len(labels)
    if n == 0:
        return ""
    ml, mr, mt, mb = 38, 8, 8, 24
    ymax = _nice_max(max(max(s[1]) for s in series) or 1)
    pw, ph = w - ml - mr, h - mt - mb
    xs = lambda i: ml + (pw * i / max(1, n - 1) if n > 1 else pw / 2)
    ys = lambda v: h - mb - ph * v / ymax
    out = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}" class="chart">', _axis(w, h, ml, mb, mt, mr, ymax)]
    if ref is not None and ref <= ymax:
        out.append(f'<line x1="{ml}" x2="{w - mr}" y1="{ys(ref):.1f}" y2="{ys(ref):.1f}" class="ref"/>')
        out.append(f'<text x="{w - mr}" y="{ys(ref) - 3:.1f}" class="tick" text-anchor="end">{_fmt(ref)}</text>')
    for j, (name, vals, col) in enumerate(series):
        pts = " ".join(f"{xs(i):.1f},{ys(v):.1f}" for i, v in enumerate(vals))
        if area_first and j == 0:
            out.append(f'<polygon points="{ml},{h - mb} {pts} {xs(n - 1):.1f},{h - mb}" fill="{col}" opacity=".18"/>')
        out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.6" stroke-linejoin="round"><title>{escape(name)}</title></polyline>')
    step = max(1, -(-n // max_x_labels))
    for i in range(0, n, step):
        out.append(f'<text x="{xs(i):.1f}" y="{h - 8}" class="tick" text-anchor="middle">{escape(labels[i])}</text>')
    out.append("</svg>")
    return "".join(out)


def hbars(rows: Sequence[Tuple[str, float, str]], w: int = 360, rowh: int = 22, vmax: Optional[float] = None, fmt=None) -> str:
    """Horizontal bars: rows = [(label, value, color)]."""
    if not rows:
        return ""
    vmax = vmax or max(r[1] for r in rows) or 1
    lw = 96
    h = rowh * len(rows) + 4
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart small">']
    for i, (lab, v, col) in enumerate(rows):
        y = i * rowh + 2
        bw = (w - lw - 58) * v / vmax
        out.append(f'<text x="{lw - 6}" y="{y + 14}" class="tick" text-anchor="end">{escape(lab)}</text>')
        out.append(f'<rect x="{lw}" y="{y + 3}" width="{max(bw, 0.5):.1f}" height="{rowh - 8}" fill="{col}" rx="2"/>')
        out.append(f'<text x="{lw + bw + 5:.1f}" y="{y + 14}" class="tick">{escape(fmt(v) if fmt else _fmt(v))}</text>')
    out.append("</svg>")
    return "".join(out)


def heatmap(grid: Sequence[Sequence[int]], row_labels: Sequence[str], w: int = 760, cell_h: int = 20) -> str:
    rows = len(grid)
    mx = max((max(r) for r in grid), default=0) or 1
    ml, mt = 38, 18
    cw = (w - ml - 4) / 24
    h = mt + rows * cell_h + 4
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="heatmap">']
    for hr in range(0, 24, 3):
        out.append(f'<text x="{ml + cw * (hr + .5):.1f}" y="12" class="tick" text-anchor="middle">{hr:02d}</text>')
    for r in range(rows):
        out.append(f'<text x="{ml - 6}" y="{mt + r * cell_h + cell_h * .68:.1f}" class="tick" text-anchor="end">{escape(row_labels[r])}</text>')
        for c in range(24):
            v = grid[r][c]
            a = 0.0 if v == 0 else 0.12 + 0.88 * (v / mx) ** 0.6
            out.append(
                f'<rect x="{ml + cw * c + .5:.1f}" y="{mt + r * cell_h + .5}" width="{cw - 1:.1f}" height="{cell_h - 1}" rx="2" fill="#d97757" opacity="{a:.2f}"><title>{escape(row_labels[r])} {c:02d}:00  {v}</title></rect>'
            )
    out.append("</svg>")
    return "".join(out)


def hour_bars(hours: Sequence[int], w: int = 760, h: int = 120) -> str:
    return bars([f"{i:02d}" for i in range(24)], [("messages", list(hours), "#2b6cb0")], w=w, h=h, max_x_labels=12)
