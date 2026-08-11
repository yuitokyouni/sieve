"""Minimal deterministic SVG plotting.

Why hand-rolled instead of matplotlib: figure bytes are sealed artifacts and
must be reproducible across machines and library versions. This module uses
nothing but the standard library, fixed-precision coordinate formatting and
explicit colors, so identical inputs produce identical SVG bytes.

Visual rules (kept small on purpose):

- light, explicit colors (reports commit to a single printed look);
- one y-axis per plot, recessive grid, thin marks;
- every multi-series plot carries a legend; single series are named by the
  panel title;
- log axes are labeled in decades and marked ``(log)`` so nobody misreads
  them as linear.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

INK = "#14181f"        # primary text
MUTED = "#5a6577"      # secondary text
GRID = "#e5eaef"       # gridlines
RULE = "#aab4c0"       # axis rules
SURFACE = "#ffffff"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a")     # validated categorical slots
BAND = "#2a78d6"       # quantile band fill (used at low opacity)
ACCENT_GRAY = "#8a94a3"

_FONT = ("font-family=\"system-ui,-apple-system,'Segoe UI',sans-serif\"")


def _n(v: float) -> str:
    """Fixed-precision coordinate: deterministic across platforms."""
    return f"{v:.2f}"


def fmt_num(v: float) -> str:
    """Tick/annotation number formatting."""
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1e5 or a < 1e-3:
        s = f"{v:.0e}"
        return s.replace("e-0", "e-").replace("e+0", "e").replace("e+", "e")
    if a >= 100:
        return f"{v:.0f}"
    if a >= 1:
        return f"{v:g}" if abs(v - round(v)) > 1e-9 else f"{int(round(v))}"
    return f"{v:.3g}"


def _nice_step(span: float, n: int) -> float:
    raw = span / max(n, 1)
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def linear_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return [lo]
    step = _nice_step(hi - lo, n)
    t = math.ceil(lo / step) * step
    out = []
    while t <= hi + 1e-9 * step:
        out.append(0.0 if abs(t) < 1e-12 * step else t)
        t += step
    return out


def log_ticks(lo: float, hi: float) -> list[float]:
    lo_e = math.floor(math.log10(lo))
    hi_e = math.ceil(math.log10(hi))
    return [10.0 ** e for e in range(lo_e, hi_e + 1)
            if lo / 1.001 <= 10.0 ** e <= hi * 1.001]


@dataclass
class _Series:
    kind: str                       # line | scatter | band | bars | vspan
    x: list[float]
    y: list[float]
    y2: list[float] | None = None   # band upper / bar base
    color: str = SERIES[0]
    width: float = 2.0
    dash: str | None = None
    radius: float = 2.4
    opacity: float = 1.0
    label: str | None = None


@dataclass
class Plot:
    """One axis + marks. Data limits are computed from what was added."""

    width: int = 660
    height: int = 330
    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    xscale: str = "linear"          # linear | log
    yscale: str = "linear"
    note: str = ""                  # small right-aligned annotation
    series: list[_Series] = field(default_factory=list)
    annotations: list[tuple[float, float, str, str, str]] = field(
        default_factory=list)       # x, y, text, anchor, color
    _xlim: tuple[float, float] | None = None
    _ylim: tuple[float, float] | None = None

    # ------------------------------------------------------------- adding
    def _check_positive(self, vals: list[float], axis: str, scale: str) -> None:
        if scale == "log" and any(v <= 0 for v in vals):
            raise ValueError(
                f"log {axis}-axis got a value <= 0; filter the data before "
                "plotting (callers must drop nonpositive points explicitly)")

    def _add(self, s: _Series) -> None:
        self._check_positive(s.x, "x", self.xscale)
        ys = list(s.y) + (list(s.y2) if s.y2 else [])
        if s.kind != "vspan":
            self._check_positive(ys, "y", self.yscale)
        self.series.append(s)

    def line(self, x, y, *, color=SERIES[0], width=2.0, dash=None,
             label=None, opacity=1.0):
        pts = [(float(a), float(b)) for a, b in zip(x, y)
               if math.isfinite(a) and math.isfinite(b)]
        if pts:
            self._add(_Series("line", [p[0] for p in pts],
                              [p[1] for p in pts], color=color, width=width,
                              dash=dash, label=label, opacity=opacity))
        return self

    def scatter(self, x, y, *, color=SERIES[0], radius=2.4, opacity=1.0,
                label=None):
        pts = [(float(a), float(b)) for a, b in zip(x, y)
               if math.isfinite(a) and math.isfinite(b)]
        if pts:
            self._add(_Series("scatter", [p[0] for p in pts],
                              [p[1] for p in pts], color=color,
                              radius=radius, opacity=opacity, label=label))
        return self

    def band(self, x, y_lo, y_hi, *, color=BAND, opacity=0.16, label=None):
        pts = [(float(a), float(b), float(c))
               for a, b, c in zip(x, y_lo, y_hi)
               if math.isfinite(a) and math.isfinite(b) and math.isfinite(c)]
        if pts:
            self._add(_Series("band", [p[0] for p in pts],
                              [p[1] for p in pts], y2=[p[2] for p in pts],
                              color=color, opacity=opacity, label=label))
        return self

    def bars(self, centers, heights, *, width_frac=0.86, color=SERIES[0],
             opacity=0.85, label=None, base=0.0):
        pts = [(float(a), float(b)) for a, b in zip(centers, heights)
               if math.isfinite(a) and math.isfinite(b)]
        if pts:
            self._add(_Series("bars", [p[0] for p in pts],
                              [p[1] for p in pts],
                              y2=[base, width_frac], color=color,
                              opacity=opacity, label=label))
        return self

    def vspan(self, x0, x1, *, color=GRID, opacity=0.6, label=None):
        self._add(_Series("vspan", [float(x0), float(x1)], [], color=color,
                          opacity=opacity, label=label))
        return self

    _hlines: list = field(default_factory=list)
    _vlines: list = field(default_factory=list)

    def hline(self, y, *, color=RULE, width=1.0, dash="4,3"):
        self._hlines.append((float(y), color, width, dash))
        return self

    def vline(self, x, *, color=RULE, width=1.0, dash="4,3"):
        self._vlines.append((float(x), color, width, dash))
        return self

    def annotate(self, x, y, text, *, anchor="start", color=MUTED):
        self.annotations.append((float(x), float(y), str(text), anchor, color))
        return self

    def xlim(self, lo, hi):
        self._xlim = (float(lo), float(hi))
        return self

    def ylim(self, lo, hi):
        self._ylim = (float(lo), float(hi))
        return self

    # ---------------------------------------------------------- rendering
    def _limits(self) -> tuple[float, float, float, float]:
        xs: list[float] = []
        ys: list[float] = []
        for s in self.series:
            if s.kind == "vspan":
                xs.extend(s.x)
                continue
            xs.extend(s.x)
            ys.extend(s.y)
            if s.kind == "band":
                ys.extend(s.y2 or [])
            if s.kind == "bars":
                ys.append(float(s.y2[0]))       # bar base
        for y, *_ in self._hlines:
            ys.append(y)
        for x, *_ in self._vlines:
            xs.append(x)
        if not xs or not ys:
            xs, ys = [0.0, 1.0], [0.0, 1.0]
        x0, x1 = (self._xlim if self._xlim else (min(xs), max(xs)))
        y0, y1 = (self._ylim if self._ylim else (min(ys), max(ys)))

        def pad(lo, hi, scale):
            if scale == "log":
                if hi <= lo:
                    hi = lo * 10
                f = (hi / lo) ** 0.04 if hi > lo else 2.0
                return lo / f, hi * f
            if hi <= lo:
                hi = lo + (abs(lo) if lo else 1.0)
            p = (hi - lo) * 0.05
            return lo - p, hi + p

        if self._xlim is None:
            x0, x1 = pad(x0, x1, self.xscale)
        if self._ylim is None:
            y0, y1 = pad(y0, y1, self.yscale)
        return x0, x1, y0, y1

    def render(self) -> str:
        m_top = 46 if (self.title or self._legend_entries()) else 14
        m_right, m_bottom, m_left = 14, 46, 58
        iw = self.width - m_left - m_right
        ih = self.height - m_top - m_bottom
        x0, x1, y0, y1 = self._limits()

        def tx(v: float) -> float:
            if self.xscale == "log":
                return m_left + iw * ((math.log10(v) - math.log10(x0))
                                      / (math.log10(x1) - math.log10(x0)))
            return m_left + iw * ((v - x0) / (x1 - x0))

        def ty(v: float) -> float:
            if self.yscale == "log":
                r = ((math.log10(v) - math.log10(y0))
                     / (math.log10(y1) - math.log10(y0)))
            else:
                r = (v - y0) / (y1 - y0)
            return m_top + ih * (1 - r)

        e: list[str] = []
        e.append(f'<rect x="0" y="0" width="{self.width}" '
                 f'height="{self.height}" fill="{SURFACE}"/>')

        xticks = (log_ticks(x0, x1) if self.xscale == "log"
                  else linear_ticks(x0, x1, 6))
        yticks = (log_ticks(y0, y1) if self.yscale == "log"
                  else linear_ticks(y0, y1, 5))
        for t in yticks:
            py = ty(t)
            e.append(f'<line x1="{_n(m_left)}" y1="{_n(py)}" '
                     f'x2="{_n(m_left + iw)}" y2="{_n(py)}" '
                     f'stroke="{GRID}" stroke-width="1"/>')
            e.append(f'<text x="{_n(m_left - 6)}" y="{_n(py + 3.4)}" '
                     f'text-anchor="end" font-size="10" fill="{MUTED}" '
                     f'{_FONT}>{fmt_num(t)}</text>')
        for t in xticks:
            px = tx(t)
            e.append(f'<line x1="{_n(px)}" y1="{_n(m_top)}" '
                     f'x2="{_n(px)}" y2="{_n(m_top + ih)}" '
                     f'stroke="{GRID}" stroke-width="1"/>')
            e.append(f'<text x="{_n(px)}" y="{_n(m_top + ih + 14)}" '
                     f'text-anchor="middle" font-size="10" fill="{MUTED}" '
                     f'{_FONT}>{fmt_num(t)}</text>')

        # vspans under the data
        for s in self.series:
            if s.kind == "vspan":
                a = max(min(s.x), x0)
                b = min(max(s.x), x1)
                if b > a:
                    e.append(f'<rect x="{_n(tx(a))}" y="{_n(m_top)}" '
                             f'width="{_n(tx(b) - tx(a))}" height="{_n(ih)}" '
                             f'fill="{s.color}" opacity="{s.opacity}"/>')

        for y, color, width, dash in self._hlines:
            if y0 <= y <= y1:
                py = ty(y)
                dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
                e.append(f'<line x1="{_n(m_left)}" y1="{_n(py)}" '
                         f'x2="{_n(m_left + iw)}" y2="{_n(py)}" '
                         f'stroke="{color}" stroke-width="{width}"'
                         f'{dash_attr}/>')
        for x, color, width, dash in self._vlines:
            if x0 <= x <= x1:
                px = tx(x)
                dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
                e.append(f'<line x1="{_n(px)}" y1="{_n(m_top)}" '
                         f'x2="{_n(px)}" y2="{_n(m_top + ih)}" '
                         f'stroke="{color}" stroke-width="{width}"'
                         f'{dash_attr}/>')

        clip_id = "c"
        e.append(f'<clipPath id="{clip_id}"><rect x="{_n(m_left)}" '
                 f'y="{_n(m_top)}" width="{_n(iw)}" height="{_n(ih)}"/>'
                 f'</clipPath>')
        e.append(f'<g clip-path="url(#{clip_id})">')
        for s in self.series:
            if s.kind == "band":
                fwd = [f"{_n(tx(a))},{_n(ty(b))}" for a, b in zip(s.x, s.y2)]
                back = [f"{_n(tx(a))},{_n(ty(b))}"
                        for a, b in zip(reversed(s.x), reversed(s.y))]
                e.append(f'<polygon points="{" ".join(fwd + back)}" '
                         f'fill="{s.color}" opacity="{s.opacity}" '
                         f'stroke="none"/>')
            elif s.kind == "bars":
                base, wf = s.y2
                bw = (iw / max(len(s.x), 1)) * wf if len(s.x) <= 1 else \
                    abs(tx(s.x[1]) - tx(s.x[0])) * wf
                for cx, h in zip(s.x, s.y):
                    top = ty(max(h, base) if self.yscale == "linear" else h)
                    bot = ty(base) if self.yscale == "linear" else m_top + ih
                    e.append(f'<rect x="{_n(tx(cx) - bw / 2)}" '
                             f'y="{_n(min(top, bot))}" width="{_n(bw)}" '
                             f'height="{_n(abs(bot - top))}" rx="1.5" '
                             f'fill="{s.color}" opacity="{s.opacity}" '
                             f'stroke="{SURFACE}" stroke-width="1"/>')
            elif s.kind == "line":
                pts = " ".join(f"{_n(tx(a))},{_n(ty(b))}"
                               for a, b in zip(s.x, s.y))
                dash = f' stroke-dasharray="{s.dash}"' if s.dash else ""
                e.append(f'<polyline points="{pts}" fill="none" '
                         f'stroke="{s.color}" stroke-width="{s.width}" '
                         f'opacity="{s.opacity}" stroke-linejoin="round" '
                         f'stroke-linecap="round"{dash}/>')
            elif s.kind == "scatter":
                for a, b in zip(s.x, s.y):
                    e.append(f'<circle cx="{_n(tx(a))}" cy="{_n(ty(b))}" '
                             f'r="{s.radius}" fill="{s.color}" '
                             f'opacity="{s.opacity}"/>')
        e.append("</g>")

        # axes on top
        e.append(f'<line x1="{_n(m_left)}" y1="{_n(m_top + ih)}" '
                 f'x2="{_n(m_left + iw)}" y2="{_n(m_top + ih)}" '
                 f'stroke="{RULE}" stroke-width="1"/>')
        e.append(f'<line x1="{_n(m_left)}" y1="{_n(m_top)}" '
                 f'x2="{_n(m_left)}" y2="{_n(m_top + ih)}" '
                 f'stroke="{RULE}" stroke-width="1"/>')

        if self.title:
            e.append(f'<text x="{_n(m_left)}" y="17" font-size="12.5" '
                     f'font-weight="600" fill="{INK}" {_FONT}>'
                     f'{_esc(self.title)}</text>')
        if self.note:
            e.append(f'<text x="{_n(self.width - m_right)}" y="17" '
                     f'text-anchor="end" font-size="10" fill="{MUTED}" '
                     f'{_FONT}>{_esc(self.note)}</text>')

        lx = m_left
        for label, color, kind in self._legend_entries():
            dash_attr = ' stroke-dasharray="4,3"' if kind == "dash" else ""
            e.append(f'<line x1="{_n(lx)}" y1="30" x2="{_n(lx + 14)}" '
                     f'y2="30" stroke="{color}" stroke-width="3"'
                     f'{dash_attr} stroke-linecap="round"/>')
            lx += 18
            e.append(f'<text x="{_n(lx)}" y="33.4" font-size="10.5" '
                     f'fill="{INK}" {_FONT}>{_esc(label)}</text>')
            lx += 7.2 * len(label) + 16

        xsuf = " (log)" if self.xscale == "log" else ""
        ysuf = " (log)" if self.yscale == "log" else ""
        if self.xlabel:
            e.append(f'<text x="{_n(m_left + iw / 2)}" '
                     f'y="{_n(self.height - 8)}" text-anchor="middle" '
                     f'font-size="11" fill="{MUTED}" {_FONT}>'
                     f'{_esc(self.xlabel + xsuf)}</text>')
        if self.ylabel:
            e.append(f'<text x="14" y="{_n(m_top + ih / 2)}" '
                     f'text-anchor="middle" font-size="11" fill="{MUTED}" '
                     f'transform="rotate(-90 14 {_n(m_top + ih / 2)})" '
                     f'{_FONT}>{_esc(self.ylabel + ysuf)}</text>')

        for ax, ay, text, anchor, color in self.annotations:
            e.append(f'<text x="{_n(tx(ax))}" y="{_n(ty(ay))}" '
                     f'text-anchor="{anchor}" font-size="10" '
                     f'fill="{color}" {_FONT}>{_esc(text)}</text>')

        body = "\n".join(e)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="0 0 {self.width} {self.height}" '
                f'width="{self.width}" height="{self.height}" '
                f'role="img">\n{body}\n</svg>')

    def _legend_entries(self) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for s in self.series:
            if s.label and s.label not in seen:
                seen.add(s.label)
                out.append((s.label, s.color,
                            "dash" if s.dash else "solid"))
        # single-series plots need no legend; the title names the series
        return out if len(out) >= 2 else []


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def panel_grid(panels: list[str], *, ncols: int = 2, panel_w: int = 660,
               panel_h: int = 330) -> str:
    """Compose rendered panel SVGs into one small-multiples SVG."""
    n = len(panels)
    ncols = max(1, min(ncols, n))
    nrows = (n + ncols - 1) // ncols
    w, h = ncols * panel_w, nrows * panel_h
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" '
             f'viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img">']
    for i, p in enumerate(panels):
        x = (i % ncols) * panel_w
        y = (i // ncols) * panel_h
        inner = p.replace('<svg xmlns="http://www.w3.org/2000/svg" ',
                          f'<svg x="{x}" y="{y}" ', 1)
        parts.append(inner)
    parts.append("</svg>")
    return "\n".join(parts)
