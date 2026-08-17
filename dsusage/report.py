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
from .i18n import current_lang, tr, tr_col

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


def _tip_attr(tip: str) -> str:
    """把提示文本编码进 data-tip 属性：换行转义为字面 \\n，避免属性值换行被规范化。"""
    return esc(tip.replace("\n", "\\n"))


# ---------------------------------------------------------------------------
# SVG 图表
# ---------------------------------------------------------------------------

def _svg_wrap(inner: str, w: int, h: int, scrollable: bool = False) -> str:
    if scrollable:
        style = f"display:block;width:{w}px;min-width:{w}px;height:auto;background:{PAPER};"
    else:
        style = f"display:block;max-width:{w}px;height:auto;background:{PAPER};"
    return (f'<svg class="fig-zoom" viewBox="0 0 {w} {h}" width="100%" role="img" '
            f'xmlns="http://www.w3.org/2000/svg" style="{style}">{inner}</svg>')


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


def _interactive_chart_fig(cfg: dict, lang: str) -> str:
    """时间序列交互图：内嵌数据 JSON，由 JS 引擎渲染（柱/线切换、时间轴缩放、点击钉住）。"""
    import json as _json
    tools = (f'<button class="mode-bar active" title="{esc(tr(lang, "mode_bar"))}">▮</button>'
             f'<button class="mode-line" title="{esc(tr(lang, "mode_line"))}">〰</button>'
             f'<span class="tool-gap"></span>'
             f'<button class="z-out" title="{esc(tr(lang, "zoom_out"))}">−</button>'
             f'<button class="z-in" title="{esc(tr(lang, "zoom_in"))}">＋</button>'
             f'<button class="z-reset" title="{esc(tr(lang, "zoom_reset"))}">↺</button>')
    data = _json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/")
    return (f'<div class="fig dsu-chart-fig"><div class="fig-tools">{tools}</div>'
            f'<script type="application/json" class="dsu-chart-data">{data}</script>'
            f'<div class="dsu-chart"></div></div>')


def _ts_chart_cfg(title: str, ylabel: str, stacked: bool, lang: str,
                  tz_sec: int, hourly: bool,
                  series: Sequence[dict]) -> dict:
    """构造交互图配置。series 项: {"name","color","points":[(t,v),...]}，t 为 UTC 秒。"""
    return {
        "title": title, "ylabel": ylabel, "stacked": stacked,
        "mode": "bar", "lang": lang, "tz": tz_sec, "hourly": hourly,
        "series": [{"name": s["name"], "color": s["color"],
                    "points": [{"t": int(t), "v": round(float(v), 6)}
                               for t, v in s["points"]]}
                   for s in series],
    }


def chart_donut(items: Sequence[Tuple[str, float]], title: str,
                cx: int = 200, cy: int = 150, r: int = 96,
                lang: Optional[str] = None) -> str:
    """环形图（模型/Key 费用占比）。"""
    lang = lang or current_lang()
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
        color = palette[i % len(palette)]
        pct = frac * 100
        tip = f"{label}\n{_fmt_full(v)}（{pct:.1f}%）"
        ang = start + 360 * frac
        if frac >= 0.99999:
            # 单一项占满整圆：路径退化（起点==终点）→ 直接用 circle
            parts.append(f'<circle class="donut-seg" data-tip="{_tip_attr(tip)}" cx="{cx}" cy="{cy}" '
                         f'r="{r}" fill="{color}" opacity="0.92" stroke="{PAPER}" stroke-width="1.5">'
                         f'<title>{esc(tip)}</title></circle>')
        else:
            a0, a1 = start, ang
            x0 = cx + r * _cos(a0)
            y0 = cy + r * _sin(a0)
            x1 = cx + r * _cos(a1)
            y1 = cy + r * _sin(a1)
            large = 1 if (a1 - a0) > 180 else 0
            path = (f"M {cx},{cy} L {x0:.1f},{y0:.1f} A {r},{r} 0 {large} 1 {x1:.1f},{y1:.1f} Z")
            parts.append(f'<path class="donut-seg" data-tip="{_tip_attr(tip)}" d="{path}" fill="{color}" '
                         f'opacity="0.92" stroke="{PAPER}" stroke-width="1.5">'
                         f'<title>{esc(tip)}</title></path>')
        start = ang
    # 中心文字（置于纸色圆盘上保证对比度）
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="34" fill="{PAPER}" '
                 f'stroke="{RULE}" stroke-width="1.2"/>')
    parts.append(f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" font-family="{FONT}" '
                 f'font-size="19" font-weight="bold" fill="{INK}">{_fmt_num(total)}</text>')
    parts.append(f'<text x="{cx}" y="{cy + 15}" text-anchor="middle" font-family="{FONT}" '
                 f'font-size="10" fill="{INK_SOFT}">{esc(tr(lang, "total_word"))}</text>')
    # 图例
    lx = cx + r + 46
    ly = cy - 70
    palette = (INK, RED, BLUE, GRAY2, GRAY3, "#7a5c3e", "#5b6b4f")
    for i, (label, v) in enumerate(items[:8]):
        pct = v / total * 100
        color = palette[i % len(palette)]
        tip = f"{label}\n{_fmt_full(v)}（{pct:.1f}%）"
        parts.append(f'<rect class="lg-sw" data-tip="{_tip_attr(tip)}" x="{lx}" y="{ly + i * 20}" '
                     f'width="11" height="11" fill="{color}">'
                     f'<title>{esc(tip)}</title></rect>')
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
        tip = f"{label}\n{_fmt_full(v)}"
        parts.append(f'<rect class="h-bar" data-tip="{_tip_attr(tip)}" x="{pad_l}" y="{y}" width="{bw:.1f}" '
                     f'height="15" fill="{color}" opacity="0.92">'
                     f'<title>{esc(tip)}</title></rect>')
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


def _table_html(table: ExportTable, lang: str, max_rows: int = 100) -> str:
    cols = [tr_col(lang, c) for c in table.columns]
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = []
    for row in table.rows[:max_rows]:
        cells = "".join(f"<td>{esc(row.get(c, ''))}</td>" for c in table.columns)
        body.append(f"<tr>{cells}</tr>")
    if len(table.rows) > max_rows:
        body.append(f'<tr><td colspan="{len(cols)}" class="note">'
                    f'{esc(tr(lang, "table_truncated", shown=max_rows, total=len(table.rows)))}</td></tr>')
    return f'<table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


_TABLE_TITLES = {
    "daily_summary": "table_daily_summary",
    "model_summary": "table_model_summary",
    "api_key_summary": "table_key_summary",
}


def render_report(ds: UsageDataset, tables: List[ExportTable], totals: Dict[str, Any],
                  meta: Optional[Dict[str, Any]] = None,
                  title: Optional[str] = None, lang: Optional[str] = None) -> str:
    lang = lang or current_lang()
    meta = meta or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    start_label = meta.get("start_date", "")
    end_label = meta.get("end_date", "")
    tz_label = meta.get("timezone", "")
    granularity = totals.get("granularity", ds.granularity())
    hourly = ds.bucket_sec == HOUR_SEC
    title = title or tr(lang, "report_title")
    html_lang = "zh-CN" if lang == "zh" else "en"

    # ---- 数据准备（时间序列：UTC 秒 → 数值）----
    series_by_t = _series_by_time(ds)
    ts_sorted = sorted(series_by_t)
    cost_rows = [(t, series_by_t[t]["cost"]) for t in ts_sorted]
    token_rows = [(t, series_by_t[t]["tokens"]) for t in ts_sorted]
    stacked = [(t, series_by_t[t]["hit"], series_by_t[t]["miss"], series_by_t[t]["response"])
               for t in ts_sorted]
    # 模型/Key 汇总（费用）
    model_t = next((t for t in tables if t.name == "model_summary"), None)
    key_t = next((t for t in tables if t.name == "api_key_summary"), None)
    daily_t = next((t for t in tables if t.name == "daily_summary"), None)
    model_items = [(r.get("模型"), float(r.get("费用") or 0)) for r in (model_t.rows if model_t else [])]
    key_items = [(r.get("API Key"), float(r.get("费用") or 0)) for r in (key_t.rows if key_t else [])]

    # ---- 头版数据（完整数字显示，不缩写）----
    stats = [
        (tr(lang, "stat_requests"), _fmt_full(float(totals.get("requests", 0))), "REQUEST"),
        (tr(lang, "stat_tokens"), _fmt_full(float(totals.get("total_tokens", 0))), "TOKENS"),
        (tr(lang, "stat_cost"), _fmt_full(float(totals.get("cost", 0))), "COST"),
        (tr(lang, "stat_cache_hit"), _fmt_full(float(totals.get("cache_hit", 0))), "HIT"),
    ]

    charts: List[str] = []
    # 交互式时间序列图：柱/线可切换（默认柱状），时间轴缩放，点击钉住
    if cost_rows and any(v > 0 for _, v in cost_rows):
        cfg = _ts_chart_cfg(tr(lang, "chart_daily_cost"), tr(lang, "cost_total"), False, lang,
                            ds.tz_sec, hourly,
                            [{"name": tr(lang, "cost_total"), "color": INK, "points": cost_rows}])
        charts.append(_interactive_chart_fig(cfg, lang))
    if stacked and any(a + b + c > 0 for _, a, b, c in stacked):
        cfg = _ts_chart_cfg(tr(lang, "chart_daily_tokens"), tr(lang, "tokens_total"), True, lang,
                            ds.tz_sec, hourly,
                            [{"name": tr(lang, "legend_hit"), "color": GRAY1,
                              "points": [(t, a) for t, a, _, _ in stacked]},
                             {"name": tr(lang, "legend_miss"), "color": GRAY2,
                              "points": [(t, b) for t, _, b, _ in stacked]},
                             {"name": tr(lang, "legend_output"), "color": INK,
                              "points": [(t, c) for t, _, _, c in stacked]}])
        charts.append(_interactive_chart_fig(cfg, lang))
    if hourly and token_rows:
        cfg = _ts_chart_cfg(tr(lang, "chart_hourly_tokens"), "Token", False, lang,
                            ds.tz_sec, hourly,
                            [{"name": tr(lang, "tokens_total"), "color": BLUE, "points": token_rows}])
        charts.append(_interactive_chart_fig(cfg, lang))
    # 静态图：环形 / 横向条形
    if model_items:
        charts.append(f'<div class="fig">{chart_donut(model_items, tr(lang, "chart_model_share"), lang=lang)}</div>')
    if key_items:
        charts.append(f'<div class="fig">{chart_hbar(key_items, tr(lang, "chart_key_rank"))}</div>')

    # ---- 数据表 ----
    tables_html = []
    for t in (daily_t, model_t, key_t):
        if t:
            tkey = _TABLE_TITLES.get(t.name)
            ttitle = tr(lang, tkey) if tkey else t.title
            tables_html.append(f'<h3 class="sec">{esc(ttitle)}</h3>{_table_html(t, lang)}')

    # ---- 报头 ----
    masthead = f"""
    <header class="masthead">
      <div class="masthead-top">
        <span>{esc(tr(lang, "report_edition", n=meta.get("edition", "1")))}</span>
        <span>{esc(now)}</span>
      </div>
      <h1 class="paper-title">{esc(title)}</h1>
      <div class="dateline">
        <span>{esc(tr(lang, "report_issue_range"))}{esc(start_label)} 〜 {esc(end_label)}</span>
        <span>{esc(tr(lang, "timezone"))} {esc(tz_label)} · {esc(tr(lang, "granularity"))} {esc(tr(lang, "report_granularity_hourly" if hourly else "report_granularity_daily"))}</span>
      </div>
    </header>
    """

    stats_html = '<div class="stats">' + "".join(
        f'<div class="stat"><div class="stat-k">{esc(k)}</div>'
        f'<div class="stat-v">{esc(v)}</div><div class="stat-s">{esc(s)}</div></div>'
        for k, v, s in stats) + '</div>'

    body = f"""
    <!DOCTYPE html>
    <html lang="{html_lang}">
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
      .fig {{ margin: 14px 0; border: 1px solid {GRAY1}; padding: 10px; background: {PAPER};
              overflow-x: auto; position: relative; }}
      .fig svg {{ border-bottom: 1px dashed {GRAY1}; }}
      .fig::-webkit-scrollbar {{ height: 8px; }}
      .fig::-webkit-scrollbar-track {{ background: {PAPER2}; }}
      .fig::-webkit-scrollbar-thumb {{ background: {GRAY2}; border-radius: 4px; }}
      /* ---- 图表工具条：柱/线切换 + 缩放控件 ---- */
      .fig-tools {{ display: flex; justify-content: flex-end; gap: 6px; margin-bottom: 6px; }}
      .fig-tools button {{ background: {PAPER}; border: 1px solid {INK_SOFT}; color: {INK};
                           font-family: {FONT}; font-size: 13px; line-height: 1;
                           padding: 4px 11px; cursor: pointer; }}
      .fig-tools button:hover {{ background: {INK}; color: {PAPER}; }}
      .fig-tools button.active {{ background: {INK}; color: {PAPER}; }}
      .fig-tools .tool-gap {{ flex: 1; }}
      .dsu-chart {{ min-height: 60px; }}
      .dsu-chart svg {{ display: block; max-width: 760px; height: auto; background: {PAPER};
                        border-bottom: 1px dashed {GRAY1}; }}
      /* ---- 自绘提示气泡（悬停查看 / 点击钉住） ---- */
      .dsu-tip {{ position: fixed; z-index: 999; max-width: 340px; padding: 8px 12px;
                  background: #fffdf6; border: 1.5px solid {INK};
                  box-shadow: 3px 3px 0 rgba(25,24,19,.22);
                  font-family: {FONT}; font-size: 12.5px; line-height: 1.55;
                  color: {INK}; white-space: pre-line; pointer-events: none;
                  display: none; }}
      .dsu-tip.pinned {{ border-color: {RED}; box-shadow: 3px 3px 0 rgba(163,59,46,.35); }}
      .dsu-tip::before {{ content: "◆"; color: {RED}; margin-right: 6px; font-size: 10px; }}
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
      <h2 class="sec">{esc(tr(lang, "report_front_page"))}</h2>
      {stats_html}
      <hr class="paper-rule">
      <h2 class="sec">{esc(tr(lang, "report_charts"))}</h2>
      {''.join(charts) or f'<p class="note">{esc(tr(lang, "no_chart_data"))}</p>'}
      <hr class="paper-rule">
      <h2 class="sec">{esc(tr(lang, "report_tables"))}</h2>
      {''.join(tables_html) or f'<p class="note">{esc(tr(lang, "no_table_data"))}</p>'}
      <div class="footer">
        {esc(tr(lang, "report_footer", ver=meta.get("version", ""), now=now))}
      </div>
    </div>
    <script>
    (function(){{
      // 自绘提示气泡：悬停查看；点击钉住（再点/Esc/点空白取消）；跟随鼠标
      var tip = document.createElement('div');
      tip.className = 'dsu-tip';
      document.body.appendChild(tip);
      var pinned = false;
      var dsuDragJustMoved = false;
      function place(x, y){{
        var r = tip.getBoundingClientRect();
        var left = x + 14, top = y + 14;
        if (left + r.width > window.innerWidth - 8) left = x - r.width - 14;
        if (top + r.height > window.innerHeight - 8) top = y - r.height - 14;
        tip.style.left = Math.max(6, left) + 'px';
        tip.style.top = Math.max(6, top) + 'px';
      }}
      function show(el, x, y){{
        tip.textContent = (el.getAttribute('data-tip') || '').replace(/\\\\n/g, '\\n');
        tip.className = 'dsu-tip' + (pinned ? ' pinned' : '');
        tip.style.display = 'block';
        place(x, y);
      }}
      function hide(){{ tip.style.display = 'none'; }}
      document.addEventListener('mouseover', function(e){{
        var t = e.target.closest('[data-tip]');
        if (t && !pinned) show(t, e.clientX, e.clientY);
      }});
      document.addEventListener('mousemove', function(e){{
        if (tip.style.display !== 'none') place(e.clientX, e.clientY);
      }});
      document.addEventListener('click', function(e){{
        if (dsuDragJustMoved){{ dsuDragJustMoved = false; return; }}
        var t = e.target.closest('[data-tip]');
        if (t){{
          pinned = !pinned;
          if (pinned) show(t, e.clientX, e.clientY); else hide();
          e.stopPropagation();
        }} else if (pinned) {{
          pinned = false; hide();
        }}
      }});
      document.addEventListener('keydown', function(e){{
        if (e.key === 'Escape' && pinned){{ pinned = false; hide(); }}
      }});
      // 移除原生 <title>，避免与自绘气泡重复提示
      document.querySelectorAll('[data-tip] title').forEach(function(t){{ t.remove(); }});
      // ---- 时间序列交互图引擎：柱/线切换（默认柱状）、时间轴缩放、分桶聚合、拖拽平移 ----
      function dsuEsc(s){{ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
      function dsuEscAttr(s){{ return dsuEsc(s).replace(/"/g,'&quot;'); }}
      function dsuFmt(v){{
        if (v >= 1e9) return (v/1e9).toFixed(1)+'B';
        if (v >= 1e6) return (v/1e6).toFixed(1)+'M';
        if (v >= 1e4) return (v/1e3).toFixed(0)+'K';
        if (v >= 1000) return (v/1e3).toFixed(1)+'K';
        if (v >= 100 || v === Math.round(v)) return v.toFixed(0);
        if (v < 1 && v !== 0) return (Math.round(v * 10000) / 10000).toFixed(4).replace(/0+$/, '').replace(/\\.$/, '');
        return v.toFixed(2);
      }}
      function dsuFmtFull(v){{ return Number(v).toLocaleString('en-US', {{ maximumFractionDigits: 6 }}); }}
      function dsuNiceTicks(vmax){{
        if (vmax <= 0) return [0];
        var step = vmax / 4, mag = Math.pow(10, Math.floor(Math.log10(step || 1))), norm = step / mag;
        var nice = mag * (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10);
        var out = [0], v = nice;
        while (v < vmax - 1e-9) {{ out.push(Math.round(v*1e6)/1e6); v += nice; }}
        if (out[out.length-1] < vmax - 1e-9) out.push(Math.round(v*1e6)/1e6);
        return out;
      }}
      function dsuTimeLabel(t, tz, lang, span){{
        var d = new Date((t + tz) * 1000);
        var mm = ('0' + (d.getUTCMonth() + 1)).slice(-2), dd = ('0' + d.getUTCDate()).slice(-2),
            hh = ('0' + d.getUTCHours()).slice(-2);
        if (span <= 3 * 86400) return (lang === 'zh' ? mm + '-' + dd + ' ' + hh + '时' : mm + '-' + dd + ' ' + hh + 'h');
        return mm + '-' + dd;
      }}
      document.querySelectorAll('.fig.dsu-chart-fig').forEach(function(fig){{
        var data = JSON.parse(fig.querySelector('.dsu-chart-data').textContent);
        var host = fig.querySelector('.dsu-chart');
        var FONT = "Georgia,'Times New Roman','Songti SC',serif";
        var INK = '#191813', INK_SOFT = '#4a463c', INK_FAINT = '#8a8172', GRAY1 = '#c9c0aa', PAPER = '#f7f2e4';
        var tmin = Infinity, tmax = -Infinity;
        data.series.forEach(function(s){{ s.points.forEach(function(p){{ if (p.t < tmin) tmin = p.t; if (p.t > tmax) tmax = p.t; }}); }});
        if (!isFinite(tmin)) tmin = 0; if (!isFinite(tmax)) tmax = tmin + 86400;
        var full = [tmin, tmax], win = [tmin, tmax];
        var mode = 'bar';
        var W = 760, H = data.stacked ? 288 : 250;
        var padL = 52, padR = 12, padT = 46, padB = data.stacked ? 58 : 36;
        var plotW = W - padL - padR, plotH = H - padT - padB;
        var anim = null;
        function clampWin(a, b){{
          var fw = full[1] - full[0];
          var w = b - a;
          if (w > fw) return [full[0], full[1]];
          if (w < fw / 60) w = fw / 60;
          if (a < full[0]) {{ a = full[0]; b = a + w; }}
          if (b > full[1]) {{ b = full[1]; a = b - w; }}
          return [a, b];
        }}
        function animateTo(nw){{
          var from = [win[0], win[1]], to = clampWin(nw[0], nw[1]);
          if (anim) cancelAnimationFrame(anim);
          var t0 = Date.now(), dur = 180;
          function frame(){{
            var k = Math.min(1, (Date.now() - t0) / dur);
            var e = 1 - Math.pow(1 - k, 3);
            win = [from[0] + (to[0] - from[0]) * e, from[1] + (to[1] - from[1]) * e];
            render();
            if (k < 1) anim = requestAnimationFrame(frame); else anim = null;
          }}
          frame();
        }}
        function binItems(){{
          var pts = [];
          data.series.forEach(function(s){{ s.points.forEach(function(p){{ if (p.t >= win[0] - 1 && p.t <= win[1] + 1) pts.push(p.t); }}); }});
          pts.sort(function(a, b){{ return a - b; }});
          var uniq = []; pts.forEach(function(t){{ if (!uniq.length || uniq[uniq.length-1] !== t) uniq.push(t); }});
          var maxBars = Math.max(3, Math.floor(plotW / 4));
          if (uniq.length <= maxBars){{
            return uniq.map(function(t){{
              var idx = data.series.map(function(s){{
                for (var i = 0; i < s.points.length; i++) if (s.points[i].t === t) return s.points[i].v;
                return 0;
              }});
              return {{ t: t, idx: idx }};
            }});
          }}
          var binW = (win[1] - win[0]) / maxBars, bins = [];
          for (var i = 0; i < maxBars; i++) bins.push({{ t: win[0] + (i + 0.5) * binW, idx: data.series.map(function(){{ return 0; }}), bin: true }});
          data.series.forEach(function(s, si){{
            s.points.forEach(function(p){{
              if (p.t < win[0] - 1 || p.t > win[1] + 1) return;
              var bi = Math.min(maxBars - 1, Math.max(0, Math.floor((p.t - win[0]) / binW)));
              bins[bi].idx[si] += p.v;
            }});
          }});
          return bins;
        }}
        function itemTip(it, si, name, v){{
          var t = dsuTimeLabel(it.t, data.tz, data.lang, win[1] - win[0]);
          var line = t + (data.series.length > 1 ? ' · ' + name : '');
          if (data.stacked){{
            return line + '\\n' + data.series.map(function(s, j){{ return s.name + ' ' + dsuFmtFull(it.idx[j]); }}).join(' · ');
          }}
          return line + '\\n' + dsuFmtFull(v);
        }}
        function render(){{
          var items = binItems();
          if (!items.length){{
            var ticks = dsuNiceTicks(0), tmax = 1;
            var parts = [];
            parts.push('<text x="' + padL + '" y="18" font-family="' + FONT + '" font-size="15" font-weight="bold" fill="' + INK + '">' + dsuEsc(data.title) + '</text>');
            ticks.forEach(function(t){{
              var y = padT + plotH - (t / tmax) * plotH;
              parts.push('<line x1="' + padL + '" y1="' + y.toFixed(1) + '" x2="' + (W - padR) + '" y2="' + y.toFixed(1) + '" stroke="' + GRAY1 + '" stroke-width="0.6" stroke-dasharray="2 3"/>');
            }});
            parts.push('<line x1="' + padL + '" y1="' + (padT + plotH) + '" x2="' + (W - padR) + '" y2="' + (padT + plotH) + '" stroke="' + INK + '" stroke-width="1.4"/>');
            parts.push('<text x="' + (padL + plotW / 2) + '" y="' + (padT + plotH / 2) + '" text-anchor="middle" font-family="' + FONT + '" font-size="13" fill="' + INK_FAINT + '">' + dsuEsc(data.lang === 'zh' ? '该时间窗口内无数据' : 'No data in this window') + '</text>');
            host.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" role="img" xmlns="http://www.w3.org/2000/svg" style="display:block;max-width:' + W + 'px;height:auto;background:' + PAPER + ';">' + parts.join('') + '</svg>';
            return;
          }}
          var vmax = 0;
          items.forEach(function(it){{
            if (data.stacked){{ var s = 0; it.idx.forEach(function(x){{ s += x; }}); if (s > vmax) vmax = s; }}
            else it.idx.forEach(function(x){{ if (x > vmax) vmax = x; }});
          }});
          var ticks = dsuNiceTicks(vmax * 1.1), tmax = ticks[ticks.length - 1] || 1;
          var span = win[1] - win[0];
          var parts = [];
          parts.push('<text x="' + padL + '" y="18" font-family="' + FONT + '" font-size="15" font-weight="bold" fill="' + INK + '">' + dsuEsc(data.title) + '</text>');
          if (data.ylabel) parts.push('<text x="' + (W - padR) + '" y="33" text-anchor="end" font-family="' + FONT + '" font-size="11" fill="' + INK_FAINT + '">' + dsuEsc(data.ylabel) + '</text>');
          ticks.forEach(function(t){{
            var y = padT + plotH - (t / tmax) * plotH;
            parts.push('<line x1="' + padL + '" y1="' + y.toFixed(1) + '" x2="' + (W - padR) + '" y2="' + y.toFixed(1) + '" stroke="' + GRAY1 + '" stroke-width="0.6" stroke-dasharray="2 3"/>');
            parts.push('<text x="' + (padL - 6) + '" y="' + (y + 4).toFixed(1) + '" text-anchor="end" font-family="' + FONT + '" font-size="10" fill="' + INK_FAINT + '">' + dsuFmt(t) + '</text>');
          }});
          parts.push('<line x1="' + padL + '" y1="' + (padT + plotH) + '" x2="' + (W - padR) + '" y2="' + (padT + plotH) + '" stroke="' + INK + '" stroke-width="1.4"/>');
          var n = items.length, slot = n ? plotW / n : plotW;
          var barW = Math.min(slot * 0.72, data.stacked ? 120 : 120);
          var step = Math.max(1, Math.floor(n / 12));
          for (var i = 0; i < n; i += step){{
            var cx = padL + slot * i + slot / 2;
            var anchor = 'middle', tx = cx;
            if (i === 0){{ anchor = 'start'; tx = padL + 10; }}
            parts.push('<text x="' + tx.toFixed(1) + '" y="' + (padT + plotH + 18) + '" text-anchor="' + anchor + '" font-family="' + FONT + '" font-size="9.5" fill="' + INK_SOFT + '">' + dsuEsc(dsuTimeLabel(items[i].t, data.tz, data.lang, span)) + '</text>');
          }}
          if (mode === 'bar'){{
            items.forEach(function(it, i){{
              var x = padL + slot * i + (slot - barW) / 2;
              if (data.stacked){{
                var acc = 0;
                data.series.forEach(function(s, si){{
                  var v = it.idx[si]; if (v <= 0) return;
                  var bh = (v / tmax) * plotH;
                  parts.push('<rect class="v-bar" data-tip="' + dsuEscAttr(itemTip(it, si, s.name, v).replace(/\\n/g, '\\\\n')) + '" x="' + x.toFixed(1) + '" y="' + (padT + plotH - acc - bh).toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + Math.max(bh, 0.4).toFixed(1) + '" fill="' + s.color + '" opacity="0.94"></rect>');
                  acc += bh;
                }});
              }} else {{
                data.series.forEach(function(s, si){{
                  var v = it.idx[si]; if (v <= 0) return;
                  var bh = (v / tmax) * plotH;
                  parts.push('<rect class="v-bar" data-tip="' + dsuEscAttr(itemTip(it, si, s.name, v).replace(/\\n/g, '\\\\n')) + '" x="' + x.toFixed(1) + '" y="' + (padT + plotH - bh).toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + Math.max(bh, 0.4).toFixed(1) + '" fill="' + s.color + '" opacity="0.92"></rect>');
                }});
              }}
            }});
          }} else {{
            var xs = items.map(function(it, i){{ return padL + slot * i + slot / 2; }});
            data.series.forEach(function(s, si){{
              var coords = [];
              items.forEach(function(it, i){{
                var v = it.idx[si]; if (v <= 0) return;
                var x = xs[i], y = padT + plotH - (v / tmax) * plotH;
                coords.push([x, y]);
                var tip = dsuEscAttr(itemTip(it, si, s.name, v).replace(/\\n/g, '\\\\n'));
                parts.push('<circle class="pt" data-tip="' + tip + '" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="2.4" fill="' + s.color + '"></circle>');
                parts.push('<circle class="pt-hit" data-tip="' + tip + '" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="13" fill="transparent"></circle>');
              }});
              if (coords.length > 1){{
                parts.push('<polyline class="line-draw" pathLength="1" points="' + coords.map(function(c){{ return c[0].toFixed(1) + ',' + c[1].toFixed(1); }}).join(' ') + '" fill="none" stroke="' + s.color + '" stroke-width="2"></polyline>');
              }}
            }});
          }}
          if (data.stacked){{
            var lg = '<g font-family="' + FONT + '" font-size="10" fill="' + INK_SOFT + '">';
            data.series.forEach(function(s, si){{
              lg += '<rect x="' + (72 + si * 150) + '" y="' + (H - 26) + '" width="10" height="10" fill="' + s.color + '"></rect>';
              lg += '<text x="' + (86 + si * 150) + '" y="' + (H - 17) + '">' + dsuEsc(s.name) + '</text>';
            }});
            parts.push(lg + '</g>');
          }}
          host.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" role="img" xmlns="http://www.w3.org/2000/svg" style="display:block;max-width:' + W + 'px;height:auto;background:' + PAPER + ';">' + parts.join('') + '</svg>';
        }}
        fig.querySelector('.mode-bar').addEventListener('click', function(e){{ e.stopPropagation(); mode = 'bar'; fig.querySelector('.mode-bar').classList.add('active'); fig.querySelector('.mode-line').classList.remove('active'); render(); }});
        fig.querySelector('.mode-line').addEventListener('click', function(e){{ e.stopPropagation(); mode = 'line'; fig.querySelector('.mode-line').classList.add('active'); fig.querySelector('.mode-bar').classList.remove('active'); render(); }});
        fig.querySelector('.z-in').addEventListener('click', function(e){{ e.stopPropagation(); var c = (win[0] + win[1]) / 2, w = (win[1] - win[0]) / 1.5; animateTo([c - w / 2, c + w / 2]); }});
        fig.querySelector('.z-out').addEventListener('click', function(e){{ e.stopPropagation(); var c = (win[0] + win[1]) / 2, w = (win[1] - win[0]) * 1.5; animateTo([c - w / 2, c + w / 2]); }});
        fig.querySelector('.z-reset').addEventListener('click', function(e){{ e.stopPropagation(); animateTo(full); }});
        fig.addEventListener('wheel', function(e){{
          e.preventDefault();
          var r = host.getBoundingClientRect();
          var fx = r.width ? (e.clientX - r.left) / r.width : 0.5;
          var tA = win[0] + (win[1] - win[0]) * fx;
          var factor = e.deltaY < 0 ? 1 / 1.5 : 1.5;
          var w = (win[1] - win[0]) * factor;
          animateTo([tA - (tA - win[0]) * factor, tA - (tA - win[0]) * factor + w]);
        }}, {{ passive: false }});
        var drag = null;
        fig.addEventListener('mousedown', function(e){{
          if (e.button === 0 && !e.target.closest('.fig-tools')){{
            var r = host.getBoundingClientRect();
            drag = {{ x: e.clientX, y: e.clientY, lx: win[0], span: win[1] - win[0], wpx: r.width || plotW }};
          }}
        }});
        document.addEventListener('mousemove', function(e){{
          if (drag){{
            var dx = e.clientX - drag.x;
            if (Math.abs(dx) > 3) dsuDragJustMoved = true;
            var dt = -dx / (drag.wpx || 1) * drag.span;
            var a = drag.lx + dt, b = a + drag.span;
            win = clampWin(a, b);
            render();
          }}
        }});
        document.addEventListener('mouseup', function(){{ drag = null; }});
        render();
      }});
    }})();
    </script>
    </body>
    </html>
    """
    return body


def build_report(ds: UsageDataset, tables: List[ExportTable], totals: Dict[str, Any],
                 out_path: Path, meta: Optional[Dict[str, Any]] = None,
                 title: Optional[str] = None, lang: Optional[str] = None) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html_text = render_report(ds, tables, totals, meta, title=title, lang=lang)
    out_path.write_text(html_text, encoding="utf-8")
    return out_path
