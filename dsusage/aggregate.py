"""从 API 数据集构建导出表格（小时明细 / 每日 / 汇总），供 Excel、CSV、Web 预览共用。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .api import DAY_SEC, HOUR_SEC, UsageDataset, sec_to_local_dt


@dataclass
class ExportTable:
    name: str                       # 工作表/文件标识（英文，用于文件名）
    title: str                      # 中文标题（工作表名）
    columns: List[str]              # 列名（中文，Excel 表头）
    rows: List[Dict[str, Any]] = field(default_factory=list)

    def add_row(self, row: Dict[str, Any]) -> None:
        self.rows.append(row)


def _display_name(ds: UsageDataset, tracking_id: str) -> str:
    return ds.api_key_names.get(tracking_id) or (tracking_id or "未归类")


def _fmt_hour(sec: int, tz_sec: int) -> str:
    return sec_to_local_dt(sec, tz_sec).strftime("%H:00")


def _fmt_date(sec: int, tz_sec: int) -> str:
    return sec_to_local_dt(sec, tz_sec).strftime("%Y-%m-%d")


def build_tables(ds: UsageDataset) -> List[ExportTable]:
    """构建导出表格集合。"""
    tables: List[ExportTable] = []
    hourly = ds.bucket_sec == HOUR_SEC

    # ---- 小时/日 明细（按 时间×Key×模型） ----
    detail = ExportTable(
        name="hourly_detail" if hourly else "daily_detail",
        title="小时明细" if hourly else "每日明细",
        columns=(["日期", "时间", "API Key", "模型", "请求数", "输入(缓存命中)",
                  "输入(缓存未命中)", "输出", "Token合计", "费用"]
                 if hourly else
                 ["日期", "API Key", "模型", "请求数", "输入(缓存命中)",
                  "输入(缓存未命中)", "输出", "Token合计", "费用"]),
    )
    for ser in ds.series:
        for b in sorted(ser.buckets, key=lambda x: x.time_sec):
            tokens = b.prompt_cache_hit + b.prompt_cache_miss + b.response + b.prompt
            if hourly:
                detail.add_row({
                    "日期": _fmt_date(b.time_sec, ds.tz_sec),
                    "时间": _fmt_hour(b.time_sec, ds.tz_sec),
                    "API Key": _display_name(ds, ser.api_key),
                    "模型": ser.model,
                    "请求数": b.request,
                    "输入(缓存命中)": b.prompt_cache_hit,
                    "输入(缓存未命中)": b.prompt_cache_miss,
                    "输出": b.response,
                    "Token合计": tokens,
                    "费用": round(b.cost, 6),
                })
            else:
                detail.add_row({
                    "日期": _fmt_date(b.time_sec, ds.tz_sec),
                    "API Key": _display_name(ds, ser.api_key),
                    "模型": ser.model,
                    "请求数": b.request,
                    "输入(缓存命中)": b.prompt_cache_hit,
                    "输入(缓存未命中)": b.prompt_cache_miss,
                    "输出": b.response,
                    "Token合计": tokens,
                    "费用": round(b.cost, 6),
                })
    if detail.rows:
        tables.append(detail)

    # ---- 每日汇总 ----
    daily = ExportTable(name="daily_summary", title="每日汇总",
                        columns=["日期", "请求数", "输入(缓存命中)", "输入(缓存未命中)",
                                 "输出", "Token合计", "费用"])
    day_rows: Dict[str, Dict[str, Any]] = {}
    for ser in ds.series:
        for b in ser.buckets:
            d = _fmt_date(b.time_sec, ds.tz_sec)
            row = day_rows.setdefault(d, {"日期": d, "请求数": 0, "输入(缓存命中)": 0,
                                          "输入(缓存未命中)": 0, "输出": 0,
                                          "Token合计": 0, "费用": 0.0})
            row["请求数"] += b.request
            row["输入(缓存命中)"] += b.prompt_cache_hit
            row["输入(缓存未命中)"] += b.prompt_cache_miss
            row["输出"] += b.response
            row["Token合计"] += b.prompt_cache_hit + b.prompt_cache_miss + b.response + b.prompt
            row["费用"] += b.cost
    for d in sorted(day_rows):
        day_rows[d]["费用"] = round(day_rows[d]["费用"], 6)
        daily.add_row(day_rows[d])
    if daily.rows:
        tables.append(daily)

    # ---- 模型汇总 ----
    model_t = ExportTable(name="model_summary", title="模型汇总",
                          columns=["模型", "请求数", "输入(缓存命中)", "输入(缓存未命中)",
                                   "输出", "Token合计", "费用", "费用占比%"])
    model_rows: Dict[str, Dict[str, Any]] = {}
    total_cost = 0.0
    for ser in ds.series:
        for b in ser.buckets:
            row = model_rows.setdefault(ser.model, {"模型": ser.model, "请求数": 0,
                                                    "输入(缓存命中)": 0, "输入(缓存未命中)": 0,
                                                    "输出": 0, "Token合计": 0, "费用": 0.0})
            row["请求数"] += b.request
            row["输入(缓存命中)"] += b.prompt_cache_hit
            row["输入(缓存未命中)"] += b.prompt_cache_miss
            row["输出"] += b.response
            row["Token合计"] += b.prompt_cache_hit + b.prompt_cache_miss + b.response + b.prompt
            row["费用"] += b.cost
            total_cost += b.cost
    for row in model_rows.values():
        row["费用"] = round(row["费用"], 6)
        row["费用占比%"] = round(row["费用"] / total_cost * 100, 2) if total_cost else 0.0
        model_t.add_row(row)
    if model_t.rows:
        tables.append(model_t)

    # ---- API Key 汇总 ----
    key_t = ExportTable(name="api_key_summary", title="API Key 汇总",
                        columns=["API Key", "请求数", "输入(缓存命中)", "输入(缓存未命中)",
                                 "输出", "Token合计", "费用", "费用占比%"])
    key_rows: Dict[str, Dict[str, Any]] = {}
    for ser in ds.series:
        name = _display_name(ds, ser.api_key)
        for b in ser.buckets:
            row = key_rows.setdefault(name, {"API Key": name, "请求数": 0,
                                             "输入(缓存命中)": 0, "输入(缓存未命中)": 0,
                                             "输出": 0, "Token合计": 0, "费用": 0.0})
            row["请求数"] += b.request
            row["输入(缓存命中)"] += b.prompt_cache_hit
            row["输入(缓存未命中)"] += b.prompt_cache_miss
            row["输出"] += b.response
            row["Token合计"] += b.prompt_cache_hit + b.prompt_cache_miss + b.response + b.prompt
            row["费用"] += b.cost
    for row in key_rows.values():
        row["费用"] = round(row["费用"], 6)
        row["费用占比%"] = round(row["费用"] / total_cost * 100, 2) if total_cost else 0.0
        key_t.add_row(row)
    if key_t.rows:
        tables.append(key_t)

    # ---- 费用汇总（按币种×Key×模型） ----
    if ds.cost_by_currency:
        cost_t = ExportTable(name="cost_detail", title="费用明细",
                             columns=["币种", "API Key", "模型", "时间", "费用"])
        for currency in sorted(ds.cost_by_currency):
            for ser in ds.cost_by_currency[currency]:
                for b in sorted(ser.buckets, key=lambda x: x.time_sec):
                    if abs(b.cost) < 1e-9:
                        continue
                    cost_t.add_row({
                        "币种": currency,
                        "API Key": _display_name(ds, ser.api_key),
                        "模型": ser.model,
                        "时间": _fmt_date(b.time_sec, ds.tz_sec)
                               + (" " + _fmt_hour(b.time_sec, ds.tz_sec) if ds.bucket_sec == HOUR_SEC else ""),
                        "费用": round(b.cost, 6),
                    })
        if cost_t.rows:
            tables.append(cost_t)

    return tables


def compute_totals(ds: UsageDataset) -> Dict[str, Any]:
    """汇总统计（Web 顶部卡片与 meta 使用）。"""
    req = hit = miss = resp = prompt = 0
    cost = 0.0
    for ser in ds.series:
        for b in ser.buckets:
            req += b.request
            hit += b.prompt_cache_hit
            miss += b.prompt_cache_miss
            resp += b.response
            prompt += b.prompt
            cost += b.cost
    return {
        "requests": req,
        "cache_hit": hit,
        "cache_miss": miss,
        "response": resp,
        "prompt": prompt,
        "total_tokens": hit + miss + resp + prompt,
        "cost": round(cost, 6),
        "granularity": ds.granularity(),
        "days": max(1, round((ds.end_sec - ds.start_sec) / DAY_SEC)),
    }
