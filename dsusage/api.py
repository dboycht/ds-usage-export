"""platform.deepseek.com 内部 API 客户端。

端点与参数语义详见 docs/api-notes.md（基于平台前端 bundle 静态分析确认）。

所有请求使用用户登录后的 Bearer Token（localStorage['userToken'].value）。
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import __version__
from .i18n import current_lang, tr

API_BASE = "https://platform.deepseek.com/api/v0"
EXPORT_PATH = "/usage/export"
AMOUNT_PATH = "/usage/by_api_key/amount"
COST_PATH = "/usage/by_api_key/cost"
SUMMARY_PATH = "/users/get_user_summary"
API_KEYS_PATH = "/users/get_api_keys"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

HOUR_SEC = 3600
DAY_SEC = 86400
# 平台 UI 前端限制为 30 天；服务端限制未知，按此窗口分片最稳妥
MAX_WINDOW_DAYS = 30


class ApiError(Exception):
    """平台 API 通用错误。"""


class AuthError(ApiError):
    """Token 无效 / 未登录。"""


class RateLimitError(ApiError):
    """请求过于频繁（429）。"""


# ---------------------------------------------------------------------------
# 时间工具
# ---------------------------------------------------------------------------

def parse_tz(tz: Any) -> int:
    """把时区参数解析为秒偏移。

    支持：int/float 秒（|v|>18 视为秒）或小时数（|v|<=18 视为小时，如 8.0 → 28800）、
    "+08:00" / "-05:30"、字符串秒数（"28800"）。
    """
    if tz is None:
        return local_tz_sec()
    if isinstance(tz, (int, float)):
        v = int(tz)
        if abs(v) <= 18:
            return v * 3600          # 视为小时
        if abs(v) > 86400:
            raise ValueError(f"时区偏移过大: {tz}")
        return v                      # 视为秒
    if isinstance(tz, str):
        s = tz.strip()
        if s in ("", "local", "auto"):
            return local_tz_sec()
        if s.startswith(("+", "-")) and ":" in s:
            sign = 1 if s[0] == "+" else -1
            hh, mm = s[1:].split(":")
            return sign * (int(hh) * 3600 + int(mm) * 60)
        try:
            v = float(s)
            return parse_tz(v)
        except ValueError:
            raise ValueError(f"无法解析时区: {tz!r}（支持 +08:00 / 28800 / 8.0）") from None
    raise ValueError(f"无法解析时区: {tz!r}")


def local_tz_sec() -> int:
    """本机时区相对 UTC 的秒偏移（用历史最小偏移近似，适用于中国用户 +8）。"""
    now = datetime.now()
    return int(now.utcoffset().total_seconds()) if now.utcoffset() else 0


def tz_label(tz_sec: int) -> str:
    sign = "+" if tz_sec >= 0 else "-"
    v = abs(tz_sec)
    return f"UTC{sign}{v // 3600:02d}:{v % 3600 // 60:02d}"


def date_to_start_sec(d: date, tz_sec: int) -> int:
    """起始日当地 00:00 对应的 UTC 秒（左闭）。"""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()) - tz_sec


def date_to_end_sec(d: date, tz_sec: int) -> int:
    """结束日次日当地 00:00 对应的 UTC 秒（右开）。"""
    return date_to_start_sec(d + timedelta(days=1), tz_sec)


def start_end_sec(start: date, end: date, tz_sec: int) -> Tuple[int, int]:
    return date_to_start_sec(start, tz_sec), date_to_end_sec(end, tz_sec)


def sec_to_local_dt(sec: int, tz_sec: int) -> datetime:
    """UTC 秒 + 时区偏移 → 当地时间（无时区信息的 naive datetime）。"""
    return datetime.fromtimestamp(sec + tz_sec, tz=timezone.utc).replace(tzinfo=None)


def iter_windows(start: date, end: date, max_days: int = MAX_WINDOW_DAYS):
    """把 [start, end] 切成 ≤max_days 天的窗口，逐段产出 (win_start, win_end)。"""
    cur = start
    while cur <= end:
        win_end = min(cur + timedelta(days=max_days - 1), end)
        yield cur, win_end
        cur = win_end + timedelta(days=1)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class Bucket:
    time_sec: int          # 桶起始（UTC 秒，配合 tz 得到当地时刻）
    request: int = 0
    prompt_cache_hit: int = 0
    prompt_cache_miss: int = 0
    response: int = 0
    prompt: int = 0        # PROMPT_TOKEN（若有）
    cost: float = 0.0      # 由 cost 序列合并而来（按币种分别存放见 costs）


@dataclass
class Series:
    api_key: str           # trackingId
    model: str
    buckets: List[Bucket] = field(default_factory=list)


@dataclass
class UsageDataset:
    """一次查询聚合后的数据集。"""
    start_sec: int
    end_sec: int
    tz_sec: int
    bucket_sec: int = 0                    # 3600=小时 / 86400=天；0=未知
    series: List[Series] = field(default_factory=list)
    # currency -> series 的费用（与 amount 的 series 可能同构）
    cost_by_currency: Dict[str, List[Series]] = field(default_factory=dict)
    api_key_names: Dict[str, str] = field(default_factory=dict)  # trackingId -> 名称
    models: List[str] = field(default_factory=list)

    def granularity(self) -> str:
        if self.bucket_sec == HOUR_SEC:
            return "hourly"
        if self.bucket_sec == DAY_SEC:
            return "daily"
        return "auto"

    def is_empty(self) -> bool:
        return not self.series and not any(self.cost_by_currency.values())


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------

class DeepSeekPlatformClient:
    """platform.deepseek.com 内部 API 客户端。"""

    def __init__(self, token: str, timeout: float = 30.0, retries: int = 4,
                 user_agent: str = DEFAULT_UA, verify: bool = True):
        if not token or not token.strip():
            raise AuthError(tr(current_lang(), "token_empty"))
        self.token = token.strip()
        self.timeout = timeout
        self.retries = max(1, retries)
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "x-app-version": "1.0.0",
            "Accept": "application/json",
            "Origin": "https://platform.deepseek.com",
            "Referer": "https://platform.deepseek.com/usage",
            "User-Agent": user_agent,
        })
        self.verify = verify

    # -- 基础请求 ----------------------------------------------------------

    def _request(self, path: str, params: Optional[Dict] = None,
                 expect_blob: bool = False, accept: Optional[str] = None) -> Any:
        url = API_BASE + path
        headers = {}
        if accept:
            headers["Accept"] = accept
        last_err: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                resp = self._session.get(url, params=params, headers=headers,
                                         timeout=self.timeout, verify=self.verify)
                if resp.status_code == 401:
                    raise AuthError(tr(current_lang(), "token_invalid"))
                if resp.status_code == 429:
                    raise RateLimitError(tr(current_lang(), "rate_limited"))
                if resp.status_code >= 500:
                    raise ApiError(f"平台服务异常 (HTTP {resp.status_code})")
                if resp.status_code != 200:
                    raise ApiError(f"请求失败 (HTTP {resp.status_code}): {resp.text[:200]}")
                if expect_blob:
                    return resp.content
                return self._parse_json(resp)
            except (requests.RequestException, ApiError) as exc:
                last_err = exc
                if isinstance(exc, (AuthError,)):
                    raise exc from None
                if attempt < self.retries - 1:
                    delay = min(2 ** attempt, 8) + 0.5
                    time.sleep(delay)
                    continue
                break
        if isinstance(last_err, RateLimitError):
            raise last_err from None
        raise ApiError(f"请求失败: {last_err}") from last_err

    @staticmethod
    def _parse_json(resp: requests.Response) -> Dict[str, Any]:
        try:
            body = resp.json()
        except ValueError:
            raise ApiError(f"响应不是合法 JSON: {resp.text[:200]}") from None
        if not isinstance(body, dict):
            raise ApiError(f"响应格式异常: {str(body)[:200]}")
        code = body.get("code")
        msg = str(body.get("msg") or "")
        if code in (40003,) or "authorization failed" in msg.lower() or "invalid token" in msg.lower():
            raise AuthError(tr(current_lang(), "token_invalid"))
        if code not in (0, None):
            raise ApiError(f"平台返回错误 code={code} msg={msg}")
        data = body.get("data") or {}
        if isinstance(data, dict) and data.get("biz_code") not in (0, None):
            raise ApiError(f"平台返回业务错误 biz_code={data.get('biz_code')} biz_msg={data.get('biz_msg')}")
        return data

    # -- 端点 --------------------------------------------------------------

    def get_user_summary(self) -> Dict[str, Any]:
        """账户摘要（余额、本月用量、总成本）。"""
        data = self._request(SUMMARY_PATH)
        return self._biz_data(data)

    def get_api_keys(self) -> List[Dict[str, Any]]:
        """API Key 列表：{trackingId, name, sensitiveId}。"""
        data = self._request(API_KEYS_PATH)
        biz = self._biz_data(data)
        if isinstance(biz, dict):
            keys = biz.get("apiKeys") or biz.get("api_keys") or []
        else:
            keys = biz or []
        return [k for k in keys if isinstance(k, dict)]

    def get_usage_amount(self, start_sec: int, end_sec: int, tz_sec: int,
                         api_key_tracking_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"start": start_sec, "end": end_sec, "tz": tz_sec}
        if api_key_tracking_ids:
            params["api_key_tracking_ids"] = ",".join(api_key_tracking_ids)
        data = self._request(AMOUNT_PATH, params)
        return self._biz_data(data)

    def get_usage_cost(self, start_sec: int, end_sec: int, tz_sec: int,
                       api_key_tracking_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"start": start_sec, "end": end_sec, "tz": tz_sec}
        if api_key_tracking_ids:
            params["api_key_tracking_ids"] = ",".join(api_key_tracking_ids)
        data = self._request(COST_PATH, params)
        return self._biz_data(data)

    def download_export_zip(self, start_sec: int, end_sec: int, tz_sec: int,
                            api_key_tracking_id: Optional[str] = None) -> bytes:
        """官方导出：返回 ZIP 二进制。"""
        params: Dict[str, Any] = {"start": start_sec, "end": end_sec, "tz": tz_sec}
        if api_key_tracking_id:
            params["api_key_tracking_id"] = api_key_tracking_id
        content = self._request(EXPORT_PATH, params, expect_blob=True, accept="application/zip")
        if content[:2] != b"PK":
            # 平台偶发以 200 返回 JSON 错误页
            raise ApiError(f"导出接口未返回 ZIP：{content[:200]!r}")
        return content

    # -- 解析 --------------------------------------------------------------

    @staticmethod
    def _norm_api_key(value: Any) -> str:
        """把 api_key 字段归一化为稳定字符串。

        平台 by_api_key 系列接口的 api_key 可能是字符串 trackingId，
        也可能是对象（如 {tracking_id/name/sensitive_id/...}），统一提取为 id 字符串。
        """
        if isinstance(value, dict):
            for key in ("tracking_id", "trackingId", "id", "api_key_id",
                        "sensitive_id", "name"):
                v = value.get(key)
                if isinstance(v, str) and v:
                    return v
            # 兜底：结构化序列化，保证可哈希且确定
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value or "")

    @staticmethod
    def _biz_data(data: Any) -> Any:
        if isinstance(data, dict):
            biz = data.get("biz_data")
            if biz is not None:
                return biz
        return data

    def parse_amount(self, biz: Any, tz_sec: int, api_key_names: Optional[Dict[str, str]] = None) -> UsageDataset:
        """把 amount 的 biz_data 解析为数据集（不含费用）。"""
        if isinstance(biz, list):
            biz = biz[0] if biz else {}
        biz = biz or {}
        ds = UsageDataset(
            start_sec=int(biz.get("start") or 0),
            end_sec=int(biz.get("end") or 0),
            tz_sec=tz_sec,
            bucket_sec=int(biz.get("bucket") or 0),
            models=list(biz.get("models") or []),
            api_key_names=dict(api_key_names or {}),
        )
        for raw in biz.get("series") or []:
            if not isinstance(raw, dict):
                continue
            ak = self._norm_api_key(raw.get("api_key"))
            model = raw.get("model") or "unknown"
            ser = Series(api_key=ak, model=model)
            for b in raw.get("buckets") or []:
                if not isinstance(b, dict):
                    continue
                usage = b.get("usage") or {}
                ser.buckets.append(Bucket(
                    time_sec=int(b.get("time") or 0),
                    request=int(usage.get("REQUEST") or 0),
                    prompt_cache_hit=int(usage.get("PROMPT_CACHE_HIT_TOKEN") or 0),
                    prompt_cache_miss=int(usage.get("PROMPT_CACHE_MISS_TOKEN") or 0),
                    response=int(usage.get("RESPONSE_TOKEN") or 0),
                    prompt=int(usage.get("PROMPT_TOKEN") or 0),
                ))
            if ser.buckets:
                ds.series.append(ser)
        return ds

    def parse_cost(self, biz: Any, tz_sec: int) -> Dict[str, List[Series]]:
        """把 cost 的 biz_data 解析为 {currency: [Series]}。"""
        if isinstance(biz, list):
            biz = biz[0] if biz else {}
        biz = biz or {}
        out: Dict[str, List[Series]] = {}
        for cur in biz.get("data") or []:
            if not isinstance(cur, dict):
                continue
            currency = cur.get("currency") or "USD"
            series: List[Series] = []
            for raw in cur.get("series") or []:
                if not isinstance(raw, dict):
                    continue
                ak = self._norm_api_key(raw.get("api_key"))
                model = raw.get("model") or "unknown"
                ser = Series(api_key=ak, model=model)
                for b in raw.get("buckets") or []:
                    if not isinstance(b, dict):
                        continue
                    try:
                        cost = float(b.get("cost") or 0)
                    except (TypeError, ValueError):
                        cost = 0.0
                    ser.buckets.append(Bucket(time_sec=int(b.get("time") or 0), cost=cost))
                if ser.buckets:
                    series.append(ser)
            if series:
                out[currency] = series
        return out

    def merge_cost_into_amount(self, ds: UsageDataset) -> None:
        """把费用序列按 (time, api_key, model) 合并进 amount 数据集。"""
        by_key: Dict[Tuple[int, str, str], List[float]] = {}
        for currency, series_list in ds.cost_by_currency.items():
            for ser in series_list:
                for b in ser.buckets:
                    by_key.setdefault((b.time_sec, ser.api_key, ser.model), []).append(b.cost)
        for ser in ds.series:
            for b in ser.buckets:
                costs = by_key.get((b.time_sec, ser.api_key, ser.model))
                if costs:
                    b.cost = sum(costs)
                else:
                    # 找不到精确匹配时回退为同时间同模型的费用（按 key 平均）
                    alt = [v for (t, _, m), vv in by_key.items()
                           if t == b.time_sec and m == ser.model for v in vv]
                    b.cost = sum(alt) / len(alt) if alt else 0.0

    # -- 高层便捷 ----------------------------------------------------------

    def check(self) -> Dict[str, Any]:
        """校验 Token 并返回账户摘要（供 login/check 使用）。"""
        return self.get_user_summary()

    def fetch_range(self, start: date, end: date, tz_sec: int,
                    granularity: str = "auto",
                    api_key_tracking_ids: Optional[List[str]] = None) -> UsageDataset:
        """按范围抓取 amount+cost 并合并。

        granularity:
          - "auto":   直接按整段请求，采用服务端返回的粒度（单日通常为小时桶）
          - "hourly": 逐日请求（24h 窗口）强制小时桶，再合并
          - "daily":  按 ≤30 天窗口分片请求，合并（服务端通常返回天桶）
        """
        if end < start:
            raise ValueError(f"结束日期 {end} 早于开始日期 {start}")

        keys = api_key_tracking_ids or None
        if granularity == "hourly":
            return self._fetch_hourly(start, end, tz_sec, keys)
        if granularity == "daily":
            return self._fetch_chunked(start, end, tz_sec, keys, force_daily=True)

        # auto：整段请求；若返回小时桶则直接可用，否则降级为逐日小时抓取？
        # 平台规则：范围 >1 天通常返回天桶，因此 auto 采用「≤30天整段」策略，
        # 用户要小时明细请显式用 hourly。
        return self._fetch_chunked(start, end, tz_sec, keys, force_daily=False)

    def _fetch_one(self, s: date, e: date, tz_sec: int,
                   keys: Optional[List[str]]) -> UsageDataset:
        s0, e0 = start_end_sec(s, e, tz_sec)
        amount_biz = self.get_usage_amount(s0, e0, tz_sec, keys)
        cost_biz = self.get_usage_cost(s0, e0, tz_sec, keys)
        names = self._api_key_names(keys)
        ds = self.parse_amount(amount_biz, tz_sec, names)
        ds.start_sec, ds.end_sec = s0, e0
        ds.cost_by_currency = self.parse_cost(cost_biz, tz_sec)
        self.merge_cost_into_amount(ds)
        return ds

    def _api_key_names(self, keys: Optional[List[str]]) -> Dict[str, str]:
        """获取 trackingId -> 名称 映射（尽力而为，失败时用 trackingId 本身）。"""
        names: Dict[str, str] = {}
        try:
            for k in self.get_api_keys():
                tid = k.get("trackingId") or k.get("tracking_id")
                if tid:
                    names[str(tid)] = k.get("name") or str(tid)
        except ApiError:
            pass
        return names

    def _fetch_chunked(self, start: date, end: date, tz_sec: int,
                       keys: Optional[List[str]], force_daily: bool) -> UsageDataset:
        parts: List[UsageDataset] = []
        for ws, we in iter_windows(start, end):
            parts.append(self._fetch_one(ws, we, tz_sec, keys))
        merged = merge_datasets(parts, tz_sec)
        if force_daily and merged.bucket_sec == HOUR_SEC:
            merged = aggregate_to_daily(merged)
        return merged

    def _fetch_hourly(self, start: date, end: date, tz_sec: int,
                      keys: Optional[List[str]]) -> UsageDataset:
        """逐日抓取，强制小时桶，并合并为连续小时序列。"""
        parts: List[UsageDataset] = []
        cur = start
        while cur <= end:
            parts.append(self._fetch_one(cur, cur, tz_sec, keys))
            cur += timedelta(days=1)
        merged = merge_datasets(parts, tz_sec)
        return merged


# ---------------------------------------------------------------------------
# 数据集合并 / 降级
# ---------------------------------------------------------------------------

def merge_datasets(parts: List[UsageDataset], tz_sec: int) -> UsageDataset:
    """合并多个数据集（按 time, api_key, model 去重合并桶）。"""
    if not parts:
        return UsageDataset(0, 0, tz_sec)
    ds = UsageDataset(
        start_sec=min(p.start_sec for p in parts),
        end_sec=max(p.end_sec for p in parts),
        tz_sec=tz_sec,
        bucket_sec=parts[0].bucket_sec,
    )
    seen_amount: Dict[Tuple[int, str, str], Bucket] = {}
    for p in parts:
        ds.models.extend(m for m in p.models if m not in ds.models)
        for name, display in p.api_key_names.items():
            ds.api_key_names.setdefault(name, display)
        for ser in p.series:
            for b in ser.buckets:
                key = (b.time_sec, ser.api_key, ser.model)
                target = seen_amount.get(key)
                if target is None:
                    target = Bucket(time_sec=b.time_sec)
                    seen_amount[key] = target
                target.request += b.request
                target.prompt_cache_hit += b.prompt_cache_hit
                target.prompt_cache_miss += b.prompt_cache_miss
                target.response += b.response
                target.prompt += b.prompt
                target.cost += b.cost
    # 保序输出 series
    order: Dict[Tuple[str, str], List[Bucket]] = {}
    for key in sorted(seen_amount, key=lambda k: (k[0], k[1], k[2])):
        order.setdefault((key[1], key[2]), []).append(seen_amount[key])
    for (ak, model), buckets in order.items():
        ds.series.append(Series(api_key=ak, model=model, buckets=buckets))

    # 合并费用（按币种）
    cost_seen: Dict[str, Dict[Tuple[int, str, str], float]] = {}
    for p in parts:
        for currency, series_list in p.cost_by_currency.items():
            m = cost_seen.setdefault(currency, {})
            for ser in series_list:
                for b in ser.buckets:
                    key = (b.time_sec, ser.api_key, ser.model)
                    m[key] = m.get(key, 0.0) + b.cost
    for currency, m in cost_seen.items():
        order_c: Dict[Tuple[str, str], List[Bucket]] = {}
        for key in sorted(m, key=lambda k: (k[0], k[1], k[2])):
            order_c.setdefault((key[1], key[2]), []).append(Bucket(time_sec=key[0], cost=m[key]))
        series_list = [Series(api_key=ak, model=model, buckets=bs) for (ak, model), bs in order_c.items()]
        ds.cost_by_currency[currency] = series_list
    return ds


def aggregate_to_daily(ds: UsageDataset) -> UsageDataset:
    """把小时桶聚合成天桶（本地时区下按天归组）。"""
    if ds.bucket_sec != HOUR_SEC:
        return ds
    new_series: List[Series] = []
    for ser in ds.series:
        days: Dict[int, Bucket] = {}
        for b in ser.buckets:
            local = sec_to_local_dt(b.time_sec, ds.tz_sec)
            day_start_sec = b.time_sec - (local.hour * 3600 + local.minute * 60 + local.second)
            target = days.get(day_start_sec)
            if target is None:
                target = Bucket(time_sec=day_start_sec)
                days[day_start_sec] = target
            target.request += b.request
            target.prompt_cache_hit += b.prompt_cache_hit
            target.prompt_cache_miss += b.prompt_cache_miss
            target.response += b.response
            target.prompt += b.prompt
            target.cost += b.cost
        new_series.append(Series(api_key=ser.api_key, model=ser.model,
                                 buckets=[days[k] for k in sorted(days)]))
    ds.series = new_series
    ds.bucket_sec = DAY_SEC
    return ds


def extract_export_zip(zip_bytes: bytes) -> Dict[str, str]:
    """解包官方导出 ZIP，返回 {文件名: 文本内容}。"""
    out: Dict[str, str] = {}
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise ApiError("导出 ZIP 损坏或格式异常") from None
    for name in zf.namelist():
        if name.lower().endswith(".csv"):
            out[name] = zf.read(name).decode("utf-8-sig", errors="replace")
    if not out:
        raise ApiError("导出 ZIP 中未找到 CSV 文件")
    return out
