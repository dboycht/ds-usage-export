"""测试：报纸风 HTML 报告生成与一键导出 (go)。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dsusage.aggregate import build_tables, compute_totals  # noqa: E402
from dsusage.api import DAY_SEC, HOUR_SEC, DeepSeekPlatformClient, date_to_start_sec  # noqa: E402
from dsusage.report import build_report, render_report  # noqa: E402
from fixtures import make_amount_biz, make_cost_biz  # noqa: E402

from test_integration import FakePlatform, make_dataset  # noqa: E402

TZ8 = 8 * 3600


def _hourly_dataset():
    c = DeepSeekPlatformClient("t")
    s = date_to_start_sec(date(2026, 7, 27), TZ8)
    amt = make_amount_biz(s, s + 3 * 3600, 3600, [
        {"api_key": {"tracking_id": "k1", "name": "KeyA"}, "model": "deepseek-chat",
         "buckets": [{"time": s, "usage": {"PROMPT_CACHE_HIT_TOKEN": 100,
                                            "PROMPT_CACHE_MISS_TOKEN": 50,
                                            "RESPONSE_TOKEN": 30, "REQUEST": 2}},
                     {"time": s + 3600, "usage": {"RESPONSE_TOKEN": 20, "REQUEST": 1}}]},
        {"api_key": {"tracking_id": "k2", "name": "KeyB"}, "model": "deepseek-reasoner",
         "buckets": [{"time": s, "usage": {"PROMPT_CACHE_MISS_TOKEN": 200,
                                            "RESPONSE_TOKEN": 80, "REQUEST": 3}}]},
    ])
    cost = make_cost_biz(s, s + 3 * 3600, 3600, "CNY", [
        {"api_key": {"tracking_id": "k1", "name": "KeyA"}, "model": "deepseek-chat",
         "buckets": [{"time": s, "cost": "0.10"}, {"time": s + 3600, "cost": "0.02"}]},
        {"api_key": {"tracking_id": "k2", "name": "KeyB"}, "model": "deepseek-reasoner",
         "buckets": [{"time": s, "cost": "0.30"}]},
    ])
    ds = c.parse_amount(amt, TZ8, {"k1": "KeyA", "k2": "KeyB"})
    ds.cost_by_currency = c.parse_cost(cost, TZ8)
    c.merge_cost_into_amount(ds)
    return ds


class TestReport(unittest.TestCase):
    def setUp(self):
        self.ds = _hourly_dataset()
        self.tables = build_tables(self.ds)
        self.totals = compute_totals(self.ds)
        self.meta = {"tool": "ds-usage-export", "version": "1.0.2",
                     "start_date": "2026-07-27", "end_date": "2026-07-27",
                     "timezone": "UTC+08:00", "tz_sec": TZ8,
                     "granularity": "hourly", "bucket_sec": HOUR_SEC,
                     "fetched_at": "2026-07-28 00:00:00", "totals": self.totals,
                     "api_key_filter": []}

    def test_render_contains_newspaper_elements(self):
        html_text = render_report(self.ds, self.tables, self.totals, self.meta)
        for token in ("DeepSeek 用量日报", "masthead", "paper-title", "头版数据",
                      "数据图表", "svg", "模型费用占比", "API Key 费用排名",
                      "小时 Token 走势", "每日费用", "数据表", "日报", "footer"):
            self.assertIn(token, html_text, f"缺少 {token}")
        # 自包含：无外部资源引用（仅允许 SVG 命名空间的 xmlns）
        self.assertNotIn("<script", html_text)
        self.assertNotIn('src="http', html_text)
        self.assertNotIn('href="http', html_text)

    def test_tooltips_and_animations(self):
        html_text = render_report(self.ds, self.tables, self.totals, self.meta)
        # 悬停提示：SVG <title>
        self.assertIn("<title>", html_text)
        self.assertGreaterEqual(html_text.count("<title>"), 8)
        # 动效 CSS
        for css in ("dsu-grow-v", "dsu-grow-h", "dsu-draw", "dsu-fade-up",
                    "donut-seg", "pt-hit", "v-bar", "h-bar"):
            self.assertIn(css, html_text, f"缺少动效 {css}")

    def test_full_number_display(self):
        """头版数据必须显示完整数字，不能缩写为 1.3B 之类。"""
        totals = dict(self.totals)
        totals.update({
            "requests": 1300000000,
            "total_tokens": 1300000000,
            "cost": 12345.6789,
            "cache_hit": 87654321,
        })
        html_text = render_report(self.ds, self.tables, totals, self.meta)
        self.assertIn("1,300,000,000", html_text)
        self.assertIn("12,345.6789", html_text)
        self.assertIn("87,654,321", html_text)
        self.assertNotIn("1.3B", html_text)

    def test_build_report_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.html"
            build_report(self.ds, self.tables, self.totals,
                         out_path=out, meta=self.meta)
            self.assertTrue(out.exists())
            content = out.read_text(encoding="utf-8")
            self.assertIn("<!DOCTYPE html>", content)
            self.assertIn("<svg", content)

    def test_daily_dataset_report(self):
        ds = make_dataset()
        tables = build_tables(ds)
        totals = compute_totals(ds)
        meta = dict(self.meta, granularity="daily", bucket_sec=DAY_SEC,
                    start_date="2026-07-01", end_date="2026-07-02")
        html_text = render_report(ds, tables, totals, meta)
        self.assertIn("svg", html_text)
        self.assertIn("每日 Token 构成", html_text)

    def test_english_report(self):
        html_text = render_report(self.ds, self.tables, self.totals, self.meta, lang="en")
        for token in ("DeepSeek Usage Daily", "Front Page", "Total Requests",
                      "Total Tokens", "Total Cost", "Cache Hits",
                      "Daily Cost", "Hourly Token Trend", "Model Cost Share",
                      "API Key Cost Ranking", "Data Tables", "Daily Summary",
                      "Model Summary", "API Key Summary", "Cache hit", "Cache miss",
                      "Output", "Total", "Generated"):
            self.assertIn(token, html_text, f"EN 缺少 {token}")
        # 英文列名
        self.assertIn("<th>Date</th>", html_text)
        self.assertIn("<th>Requests</th>", html_text)
        # 不残留中文标题
        self.assertNotIn("头版数据", html_text)

    def test_go_command(self):
        from dsusage import cli
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "exports"
            with mock.patch("dsusage.cli.DeepSeekPlatformClient", FakePlatform), \
                 mock.patch.dict(os.environ, {"DSU_CONFIG_DIR": tmp}):
                code = cli.main(["go", "--start", "2026-07-01", "--end", "2026-07-02",
                                 "--out", str(out_dir), "--token", "t"])
            self.assertEqual(code, 0)
            subdirs = list(out_dir.iterdir())
            self.assertEqual(len(subdirs), 1)
            files = {p.name for p in subdirs[0].iterdir()}
            self.assertIn("report.html", files)
            self.assertIn("usage.xlsx", files)
            self.assertIn("daily_summary.csv", files)
            report = (subdirs[0] / "report.html").read_text(encoding="utf-8")
            self.assertIn("<svg", report)


if __name__ == "__main__":
    unittest.main()
