"""报纸编辑风 HTML 图表报告生成器。

生成一个自包含（无任何外部依赖/CDN）的 HTML 文件：
- 报纸编辑部排版（衬线字体、报头、双线分隔、加粗大数字、印刷式页脚）
- 全部图表用内联 SVG 手绘：柱状图、堆叠柱、折线/面积图、环形图、横向条形图
- 主色：纸白底 + 墨黑 + 铅红点缀（报纸经典配色）
"""

from __future__ import annotations

import html as _html
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .aggregate import ExportTable
from .api import DAY_SEC, HOUR_SEC, UsageDataset, sec_to_local_dt

# ---- 报纸配色 --------------------------------------------------------------

PAPER = "#f7f2e4"
PAPER2 = "#efe7d3"
INK = "#191813"
INK_SOFT = "#4a463c"
INK_FAINT = "#8a8172"
RULE = "#191813"
RED = "#a33b2e"
BLUE = "#1f4e79"
GRAY1 = "#c9c0aa"
GRAY2 = "#9a917d"
GRAY3 = "#6d6655"

FONT = ("Georgia, 'Times New Roman', 'Songti SC', 'SimSun', 'Noto Serif SC', serif")


def esc(v: Any) -> str:
    return _html.escape(str(v if v is not None else ""))


# ---------------------------------------------------------------------------
# SVG 图表
# ---------------------------------------------------------------------------

def _svg_wrap(inner: str, w: int, h: int) -> str:
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" '
            f'xmlns="http://www.w3.org/2000/svg" style="display:block;max-width:{w}px;'
            f'height:auto;background:{PAPER};">{inner}</svg>')


def _ticks(vmax: float, n: int = 4) -> List[float]:
    """生成 0 起的「好看」刻度，且保证末档 >= vmax（数据永不超出轴上界）。"""
    if vmax <= 0:
        return [0.0]
    import math
    step = vmax / max(n, 1)
    mag = 10 ** math.floor(math.log10(step or 1))
    norm = step / mag
    nice = mag * (1 if norm <= 1 else 2 if norm <= 2 else 2.5 if norm <= 2.5 else
                  5 if norm <= 5 else 10)
    ticks: List[float] = [0.0]
    v = nice
    while v < vmax - 1e-9:
        ticks.append(round(v, 6))
        v += nice
    if ticks[-1] < vmax - 1e-9:
        ticks.append(round(v, 6))
    return ticks


def _fmt_num(v: float) -> str:
    if v >= 1e9:
        return f"{v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    if v >= 1e4:
        return f"{v / 1e3:.0f}K"
    if v >= 1000:
        return f"{v / 1e3:.1f}K"
    if v >= 100 or v == int(v):
        return f"{v:.0f}"
    return f"{v:.2f}"


def _fmt_full(v: float) -> str:
    """完整数字（千分位），供头版数据与悬停提示使用，不省略。"""
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.6f}".rstrip("0").rstrip(".") if abs(v) < 1 else f"{v:,.4f}".rstrip("0").rstrip(".")


def _nice_round(v: float) -> float:
    if v >= 1000:
        return round(v)
    if v >= 100:
        return round(v, 1)
    return round(v, 3)


def chart_bar(rows: Sequence[Tuple[str, float]], title: str,
              ylabel: str = "", h: int = 250, max_bars: int = 31) -> str:
    """竖向柱状图；项数过多时自动转为折线图。"""
    if len(rows) > max_bars:
        return chart_line(rows, title, ylabel, h=h)
    w = 760
    pad_l, pad_r, pad_t, pad_b = 52, 12, 46, 36
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    vmax = max((v for _, v in rows), default=0)
    ticks = _ticks(vmax * 1.10)   # 顶部留出数值标签空间，且刻度上界始终覆盖数据
    tmax = ticks[-1] or 1

    parts = [f'<text x="{pad_l}" y="18" font-family="{FONT}" font-size="15" '
             f'font-weight="bold" fill="{INK}">{esc(title)}</text>']
    if ylabel:
        parts.append(f'<text x="{w - pad_r}" y="33" text-anchor="end" font-family="{FONT}" font-size="11" '
                     f'fill="{INK_FAINT}">{esc(ylabel)}</text>')
    # 网格与纵轴刻度
    for t in ticks:
        y = pad_t + plot_h - (t / tmax) * plot_h
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w - pad_r}" y2="{y:.1f}" '
                     f'stroke="{GRAY1}" stroke-width="0.6" stroke-dasharray="2 3"/>')
        parts.append(f'<text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end" '
                     f'font-family="{FONT}" font-size="10" fill="{INK_FAINT}">{_fmt_num(t)}</text>')
    # 坐标轴
    parts.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{w - pad_r}" y2="{pad_t + plot_h}" '
                 f'stroke="{INK}" stroke-width="1.4"/>')
    n = len(rows)
    slot = plot_w / n
    bar_w = min(slot * 0.62, 26)
    for i, (label, v) in enumerate(rows):
        bh = (v / tmax) * plot_h if v > 0 else 0
        x = pad_l + slot * i + (slot - bar_w) / 2
        y = pad_t + plot_h - bh
        color = RED if i == len(rows) - 1 else INK
        tip = f"{label}\n{_fmt_full(v)}" + (f"（{ylabel or '费用'}）" if ylabel else "")
        parts.append(f'<rect class="v-bar" x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
                     f'height="{max(bh, 0):.1f}" fill="{color}" opacity="0.92">'
                     f'<title>{esc(tip)}</title></rect>')
        if bh > 20:
            ly = max(y - 4, pad_t + 12)
            parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{ly:.1f}" text-anchor="middle" '
                         f'font-family="{FONT}" font-size="9" fill="{INK}">{_fmt_num(v)}</text>')
        # 横轴标签：间隔显示，边缘标签向内锚定避免被裁切
        if n <= 12 or i % max(1, n // 12) == 0 or i == n - 1:
            cx = x + bar_w / 2
            if i == 0:
                anchor, tx = "start", pad_l + 10
            elif i == n - 1:
                anchor, tx = "end", w - pad_r - 4
            else:
                anchor, tx = "middle", cx
            parts.append(f'<text x="{tx:.1f}" y="{pad_t + plot_h + 18}" text-anchor="{anchor}" '
                         f'font-family="{FONT}" font-size="9.5" fill="{INK_SOFT}">{esc(label)}</text>')
    return _svg_wrap("".join(parts), w, h)


def chart_stacked(rows: Sequence[Tuple[str, float, float, float]], title: str,
                  h: int = 288, max_bars: int = 31) -> str:
    """堆叠柱状图：每项 (label, a, b, c) → 缓存命中 / 缓存未命中 / 输出。"""
    if len(rows) > max_bars:
        return chart_line([(l, a + b + c) for l, a, b, c in rows], title, "Token 合计", h=h)
    w = 760
    pad_l, pad_r, pad_t, pad_b = 52, 12, 46, 58
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    vmax = max((a + b + c for _, a, b, c in rows), default=0)
    ticks = _ticks(vmax * 1.10)
    tmax = ticks[-1] or 1
    colors = (GRAY1, GRAY2, INK)

    parts = [f'<text x="{pad_l}" y="18" font-family="{FONT}" font-size="15" '
             f'font-weight="bold" fill="{INK}">{esc(title)}</text>']
    for t in ticks:
        y = pad_t + plot_h - (t / tmax) * plot_h
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w - pad_r}" y2="{y:.1f}" '
                     f'stroke="{GRAY1}" stroke-width="0.6" stroke-dasharray="2 3"/>')
        parts.append(f'<text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end" '
                     f'font-family="{FONT}" font-size="10" fill="{INK_FAINT}">{_fmt_num(t)}</text>')
    parts.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{w - pad_r}" y2="{pad_t + plot_h}" '
                 f'stroke="{INK}" stroke-width="1.4"/>')
    n = len(rows)
    slot = plot_w / n
    bar_w = min(slot * 0.62, 26)
    for i, (label, a, b, c) in enumerate(rows):
        x = pad_l + slot * i + (slot - bar_w) / 2
        y = pad_t + plot_h
        seg_detail = (f"缓存命中 {_fmt_full(a)} · 缓存未命中 {_fmt_full(b)} · 输出 {_fmt_full(c)}\n"
                      f"Token 合计 {_fmt_full(a + b + c)}")
        for v, color, name in ((c, colors[2], "输出"), (b, colors[1], "缓存未命中"),
                               (a, colors[0], "缓存命中")):
            bh = (v / tmax) * plot_h if v > 0 else 0
            if bh > 0:
                parts.append(f'<rect class="v-bar" x="{x:.1f}" y="{y - bh:.1f}" width="{bar_w:.1f}" '
                             f'height="{bh:.1f}" fill="{color}" opacity="0.94">'
                             f'<title>{esc(f"{label} · {name} {_fmt_full(v)}\n{seg_detail}")}</title>'
                             f'</rect>')
                y -= bh
        if n <= 12 or i % max(1, n // 12) == 0 or i == n - 1:
            cx = x + bar_w / 2
            if i == 0:
                anchor, tx = "start", pad_l + 10
            elif i == n - 1:
                anchor, tx = "end", w - pad_r - 4
            else:
                anchor, tx = "middle", cx
            parts.append(f'<text x="{tx:.1f}" y="{pad_t + plot_h + 18}" text-anchor="{anchor}" '
                         f'font-family="{FONT}" font-size="9.5" fill="{INK_SOFT}">{esc(label)}</text>')
    legend = ("<g font-family='%s' font-size='10' fill='%s'>" % (FONT, INK_SOFT)
              + "".join(
                  f'<rect x="{72 + i * 150}" y="{h - 26}" width="10" height="10" fill="{colors[i]}"/>'
                  f'<text x="{86 + i * 150}" y="{h - 17}">{name}</text>'
                  for i, name in enumerate(("缓存命中", "缓存未命中", "输出")))
              + "</g>")
    parts.append(legend)
    return _svg_wrap("".join(parts), w, h)


def chart_line(rows: Sequence[Tuple[str, float]], title: str,
               ylabel: str = "", h: int = 250) -> str:
    """折线 + 面积图（长周期时间序列）。"""
    w = 760
    pad_l, pad_r, pad_t, pad_b = 52, 12, 46, 36
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b
    vmax = max((v for _, v in rows), default=0)
    ticks = _ticks(vmax * 1.10)
    tmax = ticks[-1] or 1
    n = len(rows)

    parts = [f'<text x="{pad_l}" y="18" font-family="{FONT}" font-size="15" '
             f'font-weight="bold" fill="{INK}">{esc(title)}</text>']
    if ylabel:
        parts.append(f'<text x="{w - pad_r}" y="33" text-anchor="end" font-family="{FONT}" font-size="11" '
                     f'fill="{INK_FAINT}">{esc(ylabel)}</text>')
    for t in ticks:
        y = pad_t + plot_h - (t / tmax) * plot_h
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{w - pad_r}" y2="{y:.1f}" '
                     f'stroke="{GRAY1}" stroke-width="0.6" stroke-dasharray="2 3"/>')
        parts.append(f'<text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end" '
                     f'font-family="{FONT}" font-size="10" fill="{INK_FAINT}">{_fmt_num(t)}</text>')
    parts.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{w - pad_r}" y2="{pad_t + plot_h}" '
                 f'stroke="{INK}" stroke-width="1.4"/>')

    pts: List[Tuple[float, float]] = []
    for i, (label, v) in enumerate(rows):
        x = pad_l + (plot_w * i / max(n - 1, 1))
        y = pad_t + plot_h - (v / tmax) * plot_h
        pts.append((x, y))
    if n > 1 and vmax > 0:
        area = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        poly = f"M {pts[0][0]:.1f},{pad_t + plot_h} L " + " L ".join(
            f"{x:.1f},{y:.1f}" for x, y in pts) + f" L {pts[-1][0]:.1f},{pad_t + plot_h} Z"
        parts.append(f'<polygon class="area-fade" points="{poly}" fill="{BLUE}" opacity="0.10"/>')
        parts.append(f'<polyline class="line-draw" pathLength="1" points="{area}" fill="none" '
                     f'stroke="{BLUE}" stroke-width="2"/>')
        for (x, y), (label, v) in zip(pts, rows):
            tip = esc(f"{label}\n{_fmt_full(v)}")
            parts.append(f'<circle class="pt" cx="{x:.1f}" cy="{y:.1f}" r="2.4" fill="{INK}">'
                         f'<title>{tip}</title></circle>')
            # 透明大命中区，方便悬停查看
            parts.append(f'<circle class="pt-hit" cx="{x:.1f}" cy="{y:.1f}" r="13" fill="transparent">'
                         f'<title>{tip}</title></circle>')
    # 横轴标签：边缘标签向内锚定避免被裁切
    for i, (label, v) in enumerate(rows):
        if n <= 14 or i % max(1, n // 14) == 0 or i == n - 1:
            x = pad_l + (plot_w * i / max(n - 1, 1))
            if i == 0:
                anchor, tx = "start", pad_l + 10
            elif i == n - 1:
                anchor, tx = "end", w - pad_r - 4
            else:
                anchor, tx = "middle", x
            parts.append(f'<text x="{tx:.1f}" y="{pad_t + plot_h + 18}" text-anchor="{anchor}" '
                         f'font-family="{FONT}" font-size="9.5" fill="{INK_SOFT}">{esc(label)}</text>')
    return _svg_wrap("".join(parts), w, h)


def chart_donut(items: Sequence[Tuple[str, float]], title: str,
                cx: int = 200, cy: int = 150, r: int = 96) -> str:
    """环形图（模型/Key 费用占比）。"""
    total = sum(v for _, v in items) or 1
    w, h = 760, 300
    parts = [f'<text x="20" y="24" font-family="{FONT}" font-size="15" '
             f'font-weight="bold" fill="{INK}">{esc(title)}</text>']
    palette = (INK, RED, BLUE, GRAY2, GRAY3, "#7a5c3e", "#5b6b4f")
    start = -90.0
    for i, (label, v) in enumerate(items):
        frac = v / total
        if frac <= 0:
            continue
        ang = start + 360 * frac
        a0, a1 = start, ang
        x0 = cx + r * _cos(a0)
        y0 = cy + r * _sin(a0)
        x1 = cx + r * _cos(a1)
        y1 = cy + r * _sin(a1)
        large = 1 if (a1 - a0) > 180 else 0
        path = (f"M {cx},{cy} L {x0:.1f},{y0:.1f} A {r},{r} 0 {large} 1 {x1:.1f},{y1:.1f} Z")
        color = palette[i % len(palette)]
        pct = frac * 100
        parts.append(f'<path class="donut-seg" d="{path}" fill="{color}" opacity="0.92" '
                     f'stroke="{PAPER}" stroke-width="1.5">'
                     f'<title>{esc(f"{label}\n{_fmt_full(v)}（{pct:.1f}%）")}</title></path>')
        start = ang
    # 中心文字（置于纸色圆盘上保证对比度）
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="34" fill="{PAPER}" '
                 f'stroke="{RULE}" stroke-width="1.2"/>')
    parts.append(f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" font-family="{FONT}" '
                 f'font-size="19" font-weight="bold" fill="{INK}">{_fmt_num(total)}</text>')
    parts.append(f'<text x="{cx}" y="{cy + 15}" text-anchor="middle" font-family="{FONT}" '
                 f'font-size="10" fill="{INK_SOFT}">合计</text>')
    # 图例
    lx = cx + r + 46
    ly = cy - 70
    palette = (INK, RED, BLUE, GRAY2, GRAY3, "#7a5c3e", "#5b6b4f")
    for i, (label, v) in enumerate(items[:8]):
        pct = v / total * 100
        color = palette[i % len(palette)]
        parts.append(f'<rect x="{lx}" y="{ly + i * 20}" width="11" height="11" fill="{color}">'
                     f'<title>{esc(f"{label}\n{_fmt_full(v)}（{pct:.1f}%）")}</title></rect>')
        parts.append(f'<text x="{lx + 17}" y="{ly + i * 20 + 10}" font-family="{FONT}" font-size="11" '
                     f'fill="{INK}">{esc(label)[:22]}</text>')
        parts.append(f'<text x="{lx + 230}" y="{ly + i * 20 + 10}" font-family="{FONT}" font-size="11" '
                     f'fill="{INK_SOFT}" text-anchor="end">{pct:.1f}%</text>')
    return _svg_wrap("".join(parts), w, h)


def chart_hbar(items: Sequence[Tuple[str, float]], title: str,
               h: Optional[int] = None) -> str:
    """横向条形图（API Key 排名）。"""
    items = list(items)
    n = len(items)
    row_h = 24
    pad_l, pad_r, pad_t, pad_b = 240, 80, 30, 16
    h = h or (pad_t + pad_b + max(n, 1) * row_h)
    w = 760
    plot_w = w - pad_l - pad_r
    vmax = max((v for _, v in items), default=0) or 1
    parts = [f'<text x="20" y="20" font-family="{FONT}" font-size="15" '
             f'font-weight="bold" fill="{INK}">{esc(title)}</text>']
    for i, (label, v) in enumerate(items):
        y = pad_t + i * row_h
        bw = (v / vmax) * plot_w
        color = RED if i == 0 else INK
        parts.append(f'<text x="{pad_l - 8}" y="{y + 13}" text-anchor="end" font-family="{FONT}" '
                     f'font-size="11" fill="{INK}">{esc(label)[:28]}</text>')
        parts.append(f'<rect class="h-bar" x="{pad_l}" y="{y}" width="{bw:.1f}" height="15" '
                     f'fill="{color}" opacity="0.92">'
                     f'<title>{esc(f"{label}\n{_fmt_full(v)}")}</title></rect>')
        parts.append(f'<text x="{pad_l + bw + 6:.1f}" y="{y + 13}" font-family="{FONT}" '
                     f'font-size="10.5" fill="{INK_SOFT}">{_fmt_num(v)}</text>')
    return _svg_wrap("".join(parts), w, h)


def _cos(d: float) -> float:
    import math
    return math.cos(math.radians(d))


def _sin(d: float) -> float:
    import math
    return math.sin(math.radians(d))


# ---------------------------------------------------------------------------
# 时间序列提取
# ---------------------------------------------------------------------------

def _series_by_time(ds: UsageDataset) -> Dict[int, Dict[str, float]]:
    """按桶起始秒聚合：{time_sec: {tokens, cost, requests, hit, miss, response}}"""
    out: Dict[int, Dict[str, float]] = {}
    for ser in ds.series:
        for b in ser.buckets:
            row = out.setdefault(b.time_sec, {"tokens": 0.0, "cost": 0.0, "requests": 0,
                                              "hit": 0, "miss": 0, "response": 0})
            row["tokens"] += b.prompt_cache_hit + b.prompt_cache_miss + b.response + b.prompt
            row["cost"] += b.cost
            row["requests"] += b.request
            row["hit"] += b.prompt_cache_hit
            row["miss"] += b.prompt_cache_miss
            row["response"] += b.response
    return out


def _ts_rows(ds: UsageDataset, key: str, series: Optional[Dict[int, Dict[str, float]]] = None) -> List[Tuple[str, float]]:
    series = series if series is not None else _series_by_time(ds)
    hourly = ds.bucket_sec == HOUR_SEC
    fmt = "%m-%d %H时" if hourly else "%m-%d"
    rows = []
    for t in sorted(series):
        local = sec_to_local_dt(t, ds.tz_sec)
        rows.append((local.strftime(fmt), round(series[t][key], 6)))
    return rows


# ---------------------------------------------------------------------------
# 报告组装
# ---------------------------------------------------------------------------

def _table_html(table: ExportTable, max_rows: int = 100) -> str:
    head = "".join(f"<th>{esc(c)}</th>" for c in table.columns)
    body = []
    for row in table.rows[:max_rows]:
        cells = "".join(f"<td>{esc(row.get(c, ''))}</td>" for c in table.columns)
        body.append(f"<tr>{cells}</tr>")
    if len(table.rows) > max_rows:
        body.append(f'<tr><td colspan="{len(table.columns)}" class="note">'
                    f'仅显示前 {max_rows} 行，共 {len(table.rows)} 行…</td></tr>')
    return f'<table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def render_report(ds: UsageDataset, tables: List[ExportTable], totals: Dict[str, Any],
                  meta: Optional[Dict[str, Any]] = None,
                  title: str = "DeepSeek 用量日报") -> str:
    meta = meta or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    start_label = meta.get("start_date", "")
    end_label = meta.get("end_date", "")
    tz_label = meta.get("timezone", "")
    granularity = totals.get("granularity", ds.granularity())
    hourly = ds.bucket_sec == HOUR_SEC

    # ---- 数据准备 ----
    series_by_t = _series_by_time(ds)
    cost_rows = _ts_rows(ds, "cost", series_by_t)
    token_rows = _ts_rows(ds, "tokens", series_by_t)
    stacked = []
    for t in sorted(series_by_t):
        s = series_by_t[t]
        stacked.append((_ts_label(ds, t), s["hit"], s["miss"], s["response"]))
    # 模型/Key 汇总（费用）
    model_t = next((t for t in tables if t.name == "model_summary"), None)
    key_t = next((t for t in tables if t.name == "api_key_summary"), None)
    daily_t = next((t for t in tables if t.name == "daily_summary"), None)
    model_items = [(r.get("模型"), float(r.get("费用") or 0)) for r in (model_t.rows if model_t else [])]
    key_items = [(r.get("API Key"), float(r.get("费用") or 0)) for r in (key_t.rows if key_t else [])]

    # ---- 头版数据（完整数字显示，不缩写）----
    stats = [
        ("总请求数", _fmt_full(float(totals.get("requests", 0))), "REQUEST"),
        ("Token 合计", _fmt_full(float(totals.get("total_tokens", 0))), "TOKENS"),
        ("费用合计", _fmt_full(float(totals.get("cost", 0))), "COST"),
        ("缓存命中", _fmt_full(float(totals.get("cache_hit", 0))), "HIT"),
    ]

    charts: List[str] = []
    if cost_rows and any(v > 0 for _, v in cost_rows):
        charts.append(f'<div class="fig">{chart_bar(cost_rows, "每日费用（主要货币合计）", "费用")}</div>')
    if stacked and any(a + b + c > 0 for _, a, b, c in stacked):
        charts.append(f'<div class="fig">{chart_stacked(stacked, "每日 Token 构成（缓存命中 / 未命中 / 输出）")}</div>')
    if hourly and token_rows:
        charts.append(f'<div class="fig">{chart_line(token_rows, "小时 Token 走势", "Token")}</div>')
    if model_items:
        charts.append(f'<div class="fig">{chart_donut(model_items, "模型费用占比")}</div>')
    if key_items:
        charts.append(f'<div class="fig">{chart_hbar(key_items, "API Key 费用排名")}</div>')

    # ---- 数据表 ----
    tables_html = []
    if daily_t:
        tables_html.append(f'<h3 class="sec">每日汇总</h3>{_table_html(daily_t)}')
    if model_t:
        tables_html.append(f'<h3 class="sec">模型汇总</h3>{_table_html(model_t)}')
    if key_t:
        tables_html.append(f'<h3 class="sec">API Key 汇总</h3>{_table_html(key_t)}')

    # ---- 报头 ----
    masthead = f"""
    <header class="masthead">
      <div class="masthead-top">
        <span>第 {meta.get('edition', '1')} 期 · 数据刊</span>
        <span>{now}</span>
      </div>
      <h1 class="paper-title">{esc(title)}</h1>
      <div class="dateline">
        <span>刊期范围：{esc(start_label)} 至 {esc(end_label)}</span>
        <span>时区 {esc(tz_label)} · 粒度 {esc("小时" if hourly else "天")}</span>
      </div>
    </header>
    """

    stats_html = '<div class="stats">' + "".join(
        f'<div class="stat"><div class="stat-k">{esc(k)}</div>'
        f'<div class="stat-v">{esc(v)}</div><div class="stat-s">{esc(s)}</div></div>'
        for k, v, s in stats) + '</div>'

    body = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{esc(title)} · {esc(start_label)} 至 {esc(end_label)}</title>
    <style>
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; background: {PAPER2}; color: {INK};
             font-family: {FONT}; }}
      .sheet {{ max-width: 980px; margin: 22px auto; background: {PAPER};
               border: 1px solid {RULE}; box-shadow: 6px 8px 0 rgba(25,24,19,.14);
               padding: 26px 34px 18px; }}
      .masthead {{ text-align: center; border-bottom: 3px double {RULE};
                  padding-bottom: 10px; margin-bottom: 18px; }}
      .masthead-top {{ display: flex; justify-content: space-between;
                      font-size: 11px; letter-spacing: 2px; color: {INK_SOFT};
                      border-top: 2px solid {RULE}; border-bottom: 1px solid {RULE};
                      padding: 3px 2px; margin-bottom: 10px; }}
      .paper-title {{ margin: 0; font-size: 40px; letter-spacing: 8px; font-weight: 900;
                      font-family: Georgia, 'Times New Roman', 'Songti SC', serif; }}
      .dateline {{ display: flex; justify-content: space-between; font-size: 12px;
                   color: {INK_SOFT}; margin-top: 6px; }}
      h2.sec {{ font-size: 17px; margin: 22px 0 8px; padding-left: 10px;
                border-left: 5px solid {RED}; letter-spacing: 2px; }}
      h3.sec {{ font-size: 14px; margin: 20px 0 6px; border-bottom: 1px solid {RULE};
                padding-bottom: 3px; letter-spacing: 1px; }}
      .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
                gap: 10px; margin: 16px 0 6px; }}
      .stat {{ border: 1px solid {RULE}; padding: 10px 12px 8px; position: relative;
               background: {PAPER}; }}
      .stat-k {{ font-size: 12px; color: {INK_SOFT}; letter-spacing: 1px; }}
      .stat-v {{ font-size: clamp(15px, 1.9vw, 24px); font-weight: 900; font-family: Georgia, serif;
                 margin: 2px 0; line-height: 1.15; white-space: nowrap; overflow: hidden;
                 text-overflow: clip; }}
      .stat-s {{ font-size: 9px; color: {INK_FAINT}; letter-spacing: 2px; }}
      .fig {{ margin: 14px 0; border: 1px solid {GRAY1}; padding: 10px; background: {PAPER}; }}
      .fig svg {{ border-bottom: 1px dashed {GRAY1}; }}
      /* ---- 动效（报纸编辑部风格） ---- */
      @keyframes dsu-press {{ from {{ opacity: 0; letter-spacing: 2px; }} to {{ opacity: 1; letter-spacing: 8px; }} }}
      @keyframes dsu-fade-up {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: none; }} }}
      @keyframes dsu-grow-v {{ from {{ transform: scaleY(0); }} to {{ transform: scaleY(1); }} }}
      @keyframes dsu-grow-h {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
      @keyframes dsu-draw {{ from {{ stroke-dashoffset: 1; }} to {{ stroke-dashoffset: 0; }} }}
      @keyframes dsu-fade-in {{ from {{ opacity: 0; }} to {{ opacity: 0.92; }} }}
      .paper-title {{ animation: dsu-press 1.1s ease-out both; }}
      .stats, .fig, table, h2.sec, h3.sec {{ animation: dsu-fade-up .55s ease-out both; }}
      .fig:nth-of-type(2) {{ animation-delay: .07s; }}
      .fig:nth-of-type(3) {{ animation-delay: .14s; }}
      .fig:nth-of-type(4) {{ animation-delay: .21s; }}
      .fig:nth-of-type(5) {{ animation-delay: .28s; }}
      .fig:nth-of-type(6) {{ animation-delay: .35s; }}
      svg .v-bar {{ transform-box: fill-box; transform-origin: bottom;
                    animation: dsu-grow-v .7s cubic-bezier(.2,.7,.3,1) both; }}
      svg .h-bar {{ transform-box: fill-box; transform-origin: left;
                    animation: dsu-grow-h .8s cubic-bezier(.2,.7,.3,1) both; }}
      svg .line-draw {{ stroke-dasharray: 1; animation: dsu-draw 1.3s ease-out .15s both; }}
      svg .area-fade {{ animation: dsu-fade-in 1s ease-out .4s both; }}
      svg .donut-seg {{ transform-box: fill-box; transform-origin: center;
                        animation: dsu-fade-in .8s ease-out both; }}
      svg .pt {{ animation: dsu-fade-in .5s ease-out .8s both; }}
      svg .pt-hit {{ cursor: pointer; }}
      /* 悬停反馈 */
      svg rect, svg path, svg circle {{ transition: opacity .18s ease, filter .18s ease; cursor: default; }}
      svg .v-bar:hover, svg .h-bar:hover, svg .donut-seg:hover {{ opacity: .68 !important; }}
      svg .pt:hover {{ r: 4px; opacity: 1; }}
      .fig:hover {{ box-shadow: inset 0 0 0 2px {RED}; }}
      table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; margin: 8px 0 4px; }}
      th, td {{ border: 1px solid {INK_SOFT}; padding: 5px 8px; text-align: left; }}
      th {{ background: {INK}; color: {PAPER}; font-weight: 600; letter-spacing: 1px; }}
      tr:nth-child(even) td {{ background: {PAPER2}; }}
      td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
      .note {{ color: {INK_FAINT}; font-size: 11px; font-style: italic; }}
      .footer {{ margin-top: 24px; border-top: 1px solid {RULE}; padding-top: 8px;
                 font-size: 11px; color: {INK_FAINT}; text-align: center;
                 letter-spacing: 1px; line-height: 1.7; }}
      .paper-rule {{ border: none; border-top: 3px double {RULE}; margin: 14px 0; }}
    </style>
    </head>
    <body>
    <div class="sheet">
      {masthead}
      <h2 class="sec">头版数据</h2>
      {stats_html}
      <hr class="paper-rule">
      <h2 class="sec">数据图表</h2>
      {''.join(charts) or '<p class="note">本期无可用绘图数据。</p>'}
      <hr class="paper-rule">
      <h2 class="sec">数据表</h2>
      {''.join(tables_html) or '<p class="note">本期无可用表格数据。</p>'}
      <div class="footer">
        数据来源：platform.deepseek.com 用量接口（内部 API）· 生成工具 ds-usage-export {meta.get('version', '')} ·
        生成时间 {now}<br>
        本刊数据仅供个人用量归档与分析，请勿外传；费用为平台记账口径合计，可能与账单存在尾差。
      </div>
    </div>
    </body>
    </html>
    """
    return body


def _ts_label(ds: UsageDataset, t: int) -> str:
    local = sec_to_local_dt(t, ds.tz_sec)
    return local.strftime("%m-%d %H时" if ds.bucket_sec == HOUR_SEC else "%m-%d")


def build_report(ds: UsageDataset, tables: List[ExportTable], totals: Dict[str, Any],
                 out_path: Path, meta: Optional[Dict[str, Any]] = None,
                 title: str = "DeepSeek 用量日报") -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html_text = render_report(ds, tables, totals, meta, title=title)
    out_path.write_text(html_text, encoding="utf-8")
    return out_path
