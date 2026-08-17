"""多语言支持（zh / en）。

语言选择优先级：显式传入 lang > 环境变量 DSU_LANG > 配置文件 lang > 系统 locale > zh。
"""

from __future__ import annotations

import os
from typing import Dict, Optional

DEFAULT_LANG = "zh"
SUPPORTED = ("zh", "en")

_current_lang = DEFAULT_LANG


def set_lang(lang: str) -> None:
    global _current_lang
    _current_lang = lang if lang in SUPPORTED else DEFAULT_LANG


def current_lang() -> str:
    return _current_lang


def detect_lang(config_lang: Optional[str] = None) -> str:
    """按优先级解析语言。"""
    for cand in (config_lang, os.environ.get("DSU_LANG")):
        if cand and cand in SUPPORTED:
            return cand
    # 系统 locale 提示
    for env in ("LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(env) or ""
        if v.lower().startswith(("en", "en_us")):
            return "en"
        if v.lower().startswith("zh"):
            return "zh"
    return DEFAULT_LANG


# ---------------------------------------------------------------------------
# 字符串表
# ---------------------------------------------------------------------------

_STRINGS: Dict[str, Dict[str, str]] = {
    "zh": {
        # CLI / 通用
        "token_empty": "Token 为空，请先登录：dsu login",
        "token_invalid": "Token 无效或已过期，请重新登录 platform.deepseek.com 后获取新的 userToken (dsu login)",
        "rate_limited": "请求过于频繁 (HTTP 429)，请稍后再试",
        "login_prompt": "请粘贴 platform.deepseek.com 的 userToken（输入后回车，不回显）: ",
        "token_saved": "Token 已保存到",
        "token_cancel": "未输入 Token，已取消。",
        "token_valid": "Token 有效 ✓",
        "login_again": "请重新登录：dsu login",
        "balance": "余额",
        "bonus_balance": "赠送余额",
        "monthly_tokens": "本月 Token 用量",
        "monthly_cost": "本月费用",
        "no_api_keys": "未找到 API Key。",
        "keys_count": "共 {n} 个 API Key。",
        "export_done": "导出完成 →",
        "period": "周期",
        "timezone": "时区",
        "granularity": "粒度",
        "requests": "请求数",
        "cache_hit": "缓存命中",
        "cache_miss": "缓存未命中",
        "output": "输出",
        "tokens_total": "Token 合计",
        "cost_total": "费用合计",
        "opening_report": "正在打开报告:",
        "warn_granularity": "⚠ 请求小时级，但平台对所选范围返回了天级粒度（可能该时段无小时数据）。",
        "auth_failed": "认证失败：",
        "fetch_failed": "获取失败：",
        "web_needs_flask": "Web 界面需要 flask：pip install -r requirements.txt（{e}）",
        "token_cleared": "已清除本地保存的 Token。",
        "no_saved_token": "未找到已保存的 Token。",
        "diagnose_title": "请求: amount/cost, 窗口 {d} (UTC秒 {s}~{e}, tz {tz})",
        "diagnose_saved": "完整响应已存:",
        "diagnose_dir": "诊断文件目录:",
        "diagnose_hint": "请把该目录下 diagnose_*.json 的内容或路径发给开发者核对。",
        "diagnose_api_key_dict": "api_key 字段是 dict，键: {keys}",
        "diagnose_api_key_type": "api_key 字段是 {t}: {v!r}",
        # Web 服务横幅
        "web_banner": "DeepSeek 用量导出工具 v{ver} Web 界面",
        "web_addr": "地址:",
        "web_hint": "仅本机可访问；Token 仅在浏览器→本机间传递，请勿公网暴露端口。",
        # 报告
        "report_title": "DeepSeek 用量日报",
        "report_edition": "第 {n} 期 · 数据刊",
        "report_issue_range": "刊期范围：",
        "report_granularity_hourly": "小时",
        "report_granularity_daily": "天",
        "report_front_page": "头版数据",
        "stat_requests": "总请求数",
        "stat_tokens": "Token 合计",
        "stat_cost": "费用合计",
        "stat_cache_hit": "缓存命中",
        "report_charts": "数据图表",
        "chart_daily_cost": "每日费用（主要货币合计）",
        "chart_daily_tokens": "每日 Token 构成（缓存命中 / 未命中 / 输出）",
        "chart_hourly_tokens": "小时 Token 走势",
        "chart_model_share": "模型费用占比",
        "chart_key_rank": "API Key 费用排名",
        "legend_hit": "缓存命中",
        "legend_miss": "缓存未命中",
        "legend_output": "输出",
        "report_tables": "数据表",
        "table_daily_summary": "每日汇总",
        "table_model_summary": "模型汇总",
        "table_key_summary": "API Key 汇总",
        "total_word": "合计",
        "no_chart_data": "本期无可用绘图数据。",
        "no_table_data": "本期无可用表格数据。",
        "table_truncated": "仅显示前 {shown} 行，共 {total} 行…",
        "report_footer": "数据来源：platform.deepseek.com 用量接口（内部 API）· 生成工具 ds-usage-export {ver} · 生成时间 {now}<br>本刊数据仅供个人用量归档与分析，请勿外传；费用为平台记账口径合计，可能与账单存在尾差。",
    },
    "en": {
        "token_empty": "Token is empty. Please log in first: dsu login",
        "token_invalid": "Token is invalid or expired. Please sign in to platform.deepseek.com again and get a new userToken (dsu login)",
        "rate_limited": "Too many requests (HTTP 429). Please try again later.",
        "login_prompt": "Paste your platform.deepseek.com userToken (hidden input, press Enter): ",
        "token_saved": "Token saved to",
        "token_cancel": "No token entered. Cancelled.",
        "token_valid": "Token valid ✓",
        "login_again": "Please log in again: dsu login",
        "balance": "Balance",
        "bonus_balance": "Bonus balance",
        "monthly_tokens": "Monthly token usage",
        "monthly_cost": "Monthly cost",
        "no_api_keys": "No API keys found.",
        "keys_count": "{n} API key(s) in total.",
        "export_done": "Export complete →",
        "period": "Period",
        "timezone": "Timezone",
        "granularity": "Granularity",
        "requests": "Requests",
        "cache_hit": "Cache hits",
        "cache_miss": "Cache misses",
        "output": "Output",
        "tokens_total": "Total tokens",
        "cost_total": "Total cost",
        "opening_report": "Opening report:",
        "warn_granularity": "⚠ Hourly requested, but the platform returned daily granularity for this range (maybe no hourly data).",
        "auth_failed": "Auth failed: ",
        "fetch_failed": "Fetch failed: ",
        "web_needs_flask": "Web UI requires flask: pip install -r requirements.txt ({e})",
        "token_cleared": "Saved token cleared.",
        "no_saved_token": "No saved token found.",
        "diagnose_title": "Fetch: amount/cost, window {d} (UTC {s}~{e}, tz {tz})",
        "diagnose_saved": "Full response saved to:",
        "diagnose_dir": "Diagnose files in:",
        "diagnose_hint": "Send the diagnose_*.json files (or their path) to the developer for inspection.",
        "diagnose_api_key_dict": "api_key field is a dict, keys: {keys}",
        "diagnose_api_key_type": "api_key field is {t}: {v!r}",
        "web_banner": "DeepSeek Usage Export Tool v{ver} - Web UI",
        "web_addr": "URL:",
        "web_hint": "Local access only; the token only travels between your browser and this machine. Do not expose the port publicly.",
        "report_title": "DeepSeek Usage Daily",
        "report_edition": "Vol. {n} · Data Edition",
        "report_issue_range": "Issue range: ",
        "report_granularity_hourly": "hourly",
        "report_granularity_daily": "daily",
        "report_front_page": "Front Page",
        "stat_requests": "Total Requests",
        "stat_tokens": "Total Tokens",
        "stat_cost": "Total Cost",
        "stat_cache_hit": "Cache Hits",
        "report_charts": "Charts",
        "chart_daily_cost": "Daily Cost (primary currency)",
        "chart_daily_tokens": "Daily Token Composition (cache hit / miss / output)",
        "chart_hourly_tokens": "Hourly Token Trend",
        "chart_model_share": "Model Cost Share",
        "chart_key_rank": "API Key Cost Ranking",
        "legend_hit": "Cache hit",
        "legend_miss": "Cache miss",
        "legend_output": "Output",
        "report_tables": "Data Tables",
        "table_daily_summary": "Daily Summary",
        "table_model_summary": "Model Summary",
        "table_key_summary": "API Key Summary",
        "total_word": "Total",
        "no_chart_data": "No chart data available for this issue.",
        "no_table_data": "No table data available for this issue.",
        "table_truncated": "Showing first {shown} of {total} rows…",
        "report_footer": "Source: platform.deepseek.com usage API (internal) · Tool: ds-usage-export {ver} · Generated {now}<br>For personal usage archiving and analysis only. Cost is the platform billing total; minor rounding differences may apply.",
    },
}

# 表格列名（aggregate 输出为中文列 → 英文）
COLUMNS_EN: Dict[str, str] = {
    "日期": "Date", "时间": "Time", "小时": "Hour",
    "API Key": "API Key", "模型": "Model",
    "请求数": "Requests", "输入(缓存命中)": "Input (cache hit)",
    "输入(缓存未命中)": "Input (cache miss)", "输出": "Output",
    "Token合计": "Total tokens", "费用": "Cost", "费用占比%": "Cost %",
    "币种": "Currency",
}


def tr(lang: str, key: str, **fmt) -> str:
    table = _STRINGS.get(lang if lang in SUPPORTED else DEFAULT_LANG, _STRINGS[DEFAULT_LANG])
    text = table.get(key, _STRINGS[DEFAULT_LANG].get(key, key))
    if fmt:
        try:
            text = text.format(**fmt)
        except (KeyError, IndexError):
            pass
    return text


def tr_col(lang: str, column: str) -> str:
    if lang == "en":
        return COLUMNS_EN.get(column, column)
    return column
