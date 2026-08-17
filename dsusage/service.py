"""业务编排：抓取 → 建表 → 导出，供 CLI 与 Web 复用。"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .aggregate import ExportTable, build_tables, compute_totals
from .api import (ApiError, DAY_SEC, DeepSeekPlatformClient, UsageDataset,
                  extract_export_zip, iter_windows, parse_tz, start_end_sec,
                  tz_label)
from .exporters import export_all, make_output_dir
from .parsing import OfficialRow, aggregate_official, parse_official_csv


class Service:
    """把一次「查询/导出」任务串起来。"""

    def __init__(self, client: DeepSeekPlatformClient):
        self.client = client

    # -- 抓取 --------------------------------------------------------------

    def fetch(self, start: date, end: date, tz_sec: int, granularity: str = "auto",
              api_key_tracking_ids: Optional[List[str]] = None) -> UsageDataset:
        return self.client.fetch_range(start, end, tz_sec, granularity,
                                       api_key_tracking_ids)

    # -- 官方原始导出 -------------------------------------------------------

    def fetch_raw_export(self, start: date, end: date, tz_sec: int,
                         api_key_tracking_id: Optional[str] = None,
                         progress=None) -> Dict[str, str]:
        """官方 usage/export：按 ≤30 天分片下载 zip，解包并合并同名 CSV。"""
        merged: Dict[str, List[Tuple[str, str]]] = {}  # 文件名 -> [(content)]
        parts = list(iter_windows(start, end))
        for i, (ws, we) in enumerate(parts):
            if progress:
                progress(f"下载官方导出 {ws} ~ {we} ({i + 1}/{len(parts)})")
            s0, e0 = start_end_sec(ws, we, tz_sec)
            zip_bytes = self.client.download_export_zip(s0, e0, tz_sec, api_key_tracking_id)
            files = extract_export_zip(zip_bytes)
            for name, text in files.items():
                merged.setdefault(name, []).append(text)
        # 同名 CSV 合并（去表头）
        result: Dict[str, str] = {}
        for name, contents in merged.items():
            if len(contents) == 1:
                result[name] = contents[0]
            else:
                header, body = contents[0].split("\n", 1)
                parts_body = [body.rstrip("\n")]
                for c in contents[1:]:
                    _, b = c.split("\n", 1)
                    parts_body.append(b.rstrip("\n"))
                result[name] = header + "\n" + "\n".join(parts_body)
        return result

    def parse_raw(self, raw_csv_files: Dict[str, str]) -> Dict[str, Any]:
        """解析官方 CSV（amount 为主），返回 {aggregate, tables}。"""
        agg = None
        for name in raw_csv_files:
            if "amount" in name:
                rows = parse_official_csv(raw_csv_files[name])
                agg = aggregate_official(rows)
                break
        if agg is None:
            return {"aggregate": None, "tables": []}
        tables = []
        if agg.hourly:
            tables.append(ExportTable(
                name="raw_hourly", title="官方CSV-小时明细",
                columns=["日期", "小时", "API Key", "模型", "请求数", "输入(缓存命中)",
                         "输入(缓存未命中)", "输出", "Token合计", "费用"],
                rows=[{**{c: r.get(c) for c in ["日期", "API Key", "模型", "请求数",
                                                "输入(缓存命中)", "输入(缓存未命中)",
                                                "输出", "Token合计", "费用"]},
                       "小时": f"{r.get('hour') or 0:02d}:00"} for r in agg.hourly],
            ))
        tables.append(ExportTable(
            name="raw_daily", title="官方CSV-每日明细",
            columns=["日期", "API Key", "模型", "请求数", "输入(缓存命中)",
                     "输入(缓存未命中)", "输出", "Token合计", "费用"],
            rows=[{c: r.get(c) for c in ["日期", "API Key", "模型", "请求数",
                                         "输入(缓存命中)", "输入(缓存未命中)",
                                         "输出", "Token合计", "费用"]} for r in agg.daily],
        ))
        tables.append(ExportTable(
            name="raw_daily_summary", title="官方CSV-每日汇总",
            columns=["日期", "请求数", "输入(缓存命中)", "输入(缓存未命中)",
                     "输出", "Token合计", "费用"],
            rows=agg.daily_summary,
        ))
        return {"aggregate": agg, "tables": tables}

    # -- 完整导出 ----------------------------------------------------------

    def run_export(self, start: date, end: date, tz_sec: int,
                   granularity: str = "auto",
                   formats: Optional[List[str]] = None,
                   out_dir: Optional[Path] = None,
                   include_raw: bool = False,
                   api_key_tracking_ids: Optional[List[str]] = None,
                   progress=None) -> Dict[str, Any]:
        """执行一次完整导出，返回结果摘要 dict。

        formats: xlsx / csv / html 的组合。
        """
        formats = formats or ["xlsx"]
        ds = self.fetch(start, end, tz_sec, granularity, api_key_tracking_ids)
        tables = build_tables(ds)
        totals = compute_totals(ds)

        meta = {
            "tool": "ds-usage-export",
            "version": _version(),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": tz_label(tz_sec),
            "tz_sec": tz_sec,
            "granularity": ds.granularity(),
            "bucket_sec": ds.bucket_sec,
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "totals": totals,
            "api_key_filter": api_key_tracking_ids or [],
        }

        raw_files: Dict[str, str] = {}
        if include_raw:
            if progress:
                progress("获取官方原始导出 (usage/export)")
            raw_files = self.fetch_raw_export(start, end, tz_sec,
                                              api_key_tracking_ids[0] if api_key_tracking_ids else None,
                                              progress)
            meta["raw_files"] = sorted(raw_files.keys())

        out_dir = make_output_dir(out_dir or Path("exports"), start.isoformat(),
                                  end.isoformat(), tz_sec)
        files = export_all(out_dir, tables, [f for f in formats if f != "html"], meta, raw_files)

        if "html" in formats:
            from .report import build_report
            from .i18n import current_lang
            if progress:
                progress("排版报纸风 HTML 图表报告")
            report_path = build_report(ds, tables, totals,
                                       out_path=out_dir / "report.html",
                                       meta=meta, lang=current_lang())
            files.setdefault("html", []).append(report_path.name)

        return {
            "ok": True,
            "out_dir": str(out_dir),
            "files": files,
            "tables": tables,
            "totals": totals,
            "dataset": ds,
            "meta": meta,
            "raw_files": raw_files,
        }


def _version() -> str:
    from . import __version__
    return __version__
