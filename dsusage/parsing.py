"""官方导出 CSV（usage/export 返回的 zip 内 amount-*.csv / cost-*.csv）解析。

CSV 列随平台版本可能变化（常见列：utc_date, model, api_key_name, type, price, amount），
本模块按表头自适应，并兼容 utc_date 的多种格式（YYYY-MM-DD / YYYYMMDD / 带时间）。
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_DATE_ONLY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DATE_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DATETIME_SEP = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):")


@dataclass
class OfficialRow:
    """官方 CSV 中的一行（已归一化）。"""
    date: str                 # YYYY-MM-DD
    hour: Optional[int] = None  # 0-23，CSV 无时间信息时为 None
    model: str = ""
    api_key_name: str = ""
    type: str = ""
    price: float = 0.0
    amount: float = 0.0
    raw: Dict[str, str] = field(default_factory=dict)


def normalize_utc_date(value: str) -> str:
    """把 utc_date 归一化为 YYYY-MM-DD。"""
    value = (value or "").strip()
    m = _DATE_ONLY.match(value)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DATE_COMPACT.match(value)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = _DATETIME_SEP.match(value)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return value


def parse_hour_of_utc_date(value: str) -> Optional[int]:
    """从 utc_date 提取小时（如 "2026-07-01 03:00:00" → 3）；无时间返回 None。"""
    value = (value or "").strip()
    m = _DATETIME_SEP.match(value)
    if m:
        return int(m.group(4))
    return None


def _to_float(v: Optional[str]) -> float:
    try:
        return float((v or "").strip() or 0)
    except ValueError:
        return 0.0


def parse_official_csv(text: str) -> List[OfficialRow]:
    """解析官方 amount/cost CSV 为归一化行列表。"""
    text = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    rows: List[OfficialRow] = []
    for raw in reader:
        if not raw:
            continue
        r = OfficialRow(
            date=normalize_utc_date(raw.get("utc_date") or ""),
            hour=parse_hour_of_utc_date(raw.get("utc_date") or ""),
            model=(raw.get("model") or "").strip(),
            api_key_name=(raw.get("api_key_name") or raw.get("api_key") or "").strip(),
            type=(raw.get("type") or "").strip(),
            price=_to_float(raw.get("price")),
            amount=_to_float(raw.get("amount")),
            raw=raw,
        )
        if r.date or r.type:
            rows.append(r)
    return rows


_TYPE_MAP = {
    "output_tokens": "response",
    "input_cache_hit_tokens": "cache_hit",
    "input_cache_miss_tokens": "cache_miss",
    "input_tokens": "prompt",
    "prompt_tokens": "prompt",
    "request_count": "request",
    "request": "request",
}


@dataclass
class OfficialAggregate:
    """官方 CSV 聚合结果：小时/日粒度明细 + 汇总。"""
    hourly: List[Dict] = field(default_factory=list)   # 有小时信息时
    daily: List[Dict] = field(default_factory=list)    # 按 日期×模型×Key
    daily_summary: List[Dict] = field(default_factory=list)
    totals: Dict[str, float] = field(default_factory=dict)

    def has_hourly(self) -> bool:
        return any(r.get("hour") is not None for r in self.hourly)


def aggregate_official(rows: List[OfficialRow]) -> OfficialAggregate:
    """把官方 CSV 行聚合成多张表（与 API 数据集表格同构）。"""
    agg = OfficialAggregate()
    # 1) 小时级（仅当 CSV 带时间）
    hourly_map: Dict[tuple, Dict] = {}
    daily_map: Dict[tuple, Dict] = {}
    totals = {"request": 0.0, "cache_hit": 0.0, "cache_miss": 0.0,
              "response": 0.0, "prompt": 0.0, "cost": 0.0}

    def _bump(target: Dict[tuple, Dict], key: tuple, kind: str, amount: float, price: float):
        row = target.get(key)
        if row is None:
            row = {"request": 0.0, "cache_hit": 0.0, "cache_miss": 0.0,
                   "response": 0.0, "prompt": 0.0, "cost": 0.0}
            target[key] = row
        mapped = _TYPE_MAP.get(kind, "prompt" if kind else "prompt")
        if mapped == "request":
            row["request"] += amount
            row["cost"] += price * amount
        else:
            row[mapped] += amount
            row["cost"] += price * amount
        totals[mapped] += amount

    for r in rows:
        if r.type == "request_count":
            kind = "request"
        else:
            kind = r.type
        if r.hour is not None:
            _bump(hourly_map, (r.date, r.hour, r.model, r.api_key_name), kind, r.amount, r.price)
        _bump(daily_map, (r.date, r.model, r.api_key_name), kind, r.amount, r.price)

    def _to_row(key: tuple, d: Dict, has_hour: bool) -> Dict:
        row = {
            "date": key[0],
            "api_key_name": key[-1],
            "model": key[-2],
            "requests": int(d["request"]),
            "cache_hit": int(d["cache_hit"]),
            "cache_miss": int(d["cache_miss"]),
            "response": int(d["response"]),
            "prompt": int(d["prompt"]),
            "total_tokens": int(d["cache_hit"] + d["cache_miss"] + d["response"] + d["prompt"]),
            "cost": round(d["cost"], 6),
        }
        if has_hour:
            row["hour"] = key[1]
        return row

    for key in sorted(hourly_map):
        agg.hourly.append(_to_row(key, hourly_map[key], True))
    for key in sorted(daily_map):
        agg.daily.append(_to_row(key, daily_map[key], False))

    # 纯每日汇总
    day_totals: Dict[str, Dict] = {}
    for row in agg.daily:
        t = day_totals.setdefault(row["date"], {"requests": 0, "cache_hit": 0, "cache_miss": 0,
                                                "response": 0, "prompt": 0, "total_tokens": 0, "cost": 0.0})
        for f in ("requests", "cache_hit", "cache_miss", "response", "prompt", "total_tokens"):
            t[f] += row[f]
        t["cost"] += row["cost"]
    agg.daily_summary = [{"date": d, **t} for d, t in sorted(day_totals.items())]

    agg.totals = {
        "requests": int(totals["request"]),
        "cache_hit": int(totals["cache_hit"]),
        "cache_miss": int(totals["cache_miss"]),
        "response": int(totals["response"]),
        "prompt": int(totals["prompt"]),
        "total_tokens": int(totals["cache_hit"] + totals["cache_miss"] + totals["response"] + totals["prompt"]),
        "cost": round(totals["cost"], 6),
    }
    return agg
