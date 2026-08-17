"""集成测试：Web 接口与 CLI 全链路（使用假平台客户端，无需网络/真实 Token）。"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dsusage.api import DeepSeekPlatformClient, date_to_start_sec  # noqa: E402
from fixtures import make_amount_biz, make_cost_biz  # noqa: E402

TZ8 = 8 * 3600


def make_dataset():
    c = DeepSeekPlatformClient("t")
    s1 = date_to_start_sec(date(2026, 7, 1), TZ8)
    s2 = date_to_start_sec(date(2026, 7, 2), TZ8)
    amt = make_amount_biz(s1, s2 + 86400, 86400, [
        {"api_key": "k1", "model": "deepseek-chat",
         "buckets": [{"time": s1, "usage": {"PROMPT_CACHE_HIT_TOKEN": 10,
                                             "RESPONSE_TOKEN": 5, "REQUEST": 1}}]},
        {"api_key": "k2", "model": "deepseek-reasoner",
         "buckets": [{"time": s2, "usage": {"PROMPT_CACHE_MISS_TOKEN": 20,
                                             "RESPONSE_TOKEN": 8, "REQUEST": 2}}]},
    ])
    cost = make_cost_biz(s1, s2 + 86400, 86400, "CNY", [
        {"api_key": "k1", "model": "deepseek-chat", "buckets": [{"time": s1, "cost": "0.01"}]},
        {"api_key": "k2", "model": "deepseek-reasoner", "buckets": [{"time": s2, "cost": "0.02"}]},
    ])
    ds = c.parse_amount(amt, TZ8, {"k1": "KeyA", "k2": "KeyB"})
    ds.cost_by_currency = c.parse_cost(cost, TZ8)
    c.merge_cost_into_amount(ds)
    return ds


class FakePlatform:
    """替代 DeepSeekPlatformClient 的假客户端。"""

    def __init__(self, token: str):
        self.token = token

    def get_user_summary(self):
        return {
            "normal_wallets": [{"currency": "CNY", "balance": "100.00"}],
            "bonus_wallets": [],
            "monthly_token_usage": "12345",
            "monthly_costs": [{"currency": "CNY", "amount": "0.50"}],
        }

    def check(self):
        return self.get_user_summary()

    def get_api_keys(self):
        return [
            {"trackingId": "k1", "name": "KeyA", "sensitiveId": "sk-a***"},
            {"trackingId": "k2", "name": "KeyB", "sensitiveId": "sk-b***"},
        ]

    def fetch_range(self, start, end, tz_sec, granularity="auto", api_key_tracking_ids=None):
        return make_dataset()

    def download_export_zip(self, *args, **kwargs):
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("amount-2026-07-01_2026-07-02.csv",
                       "utc_date,model,api_key_name,type,price,amount\n"
                       "2026-07-01,deepseek-chat,KeyA,output_tokens,0.000002,100\n")
        return buf.getvalue()


class TestWebApp(unittest.TestCase):
    def setUp(self):
        from dsusage.webapp import create_app
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(exports_dir=Path(self.tmp.name) / "exports")
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        patcher = mock.patch("dsusage.webapp.DeepSeekPlatformClient", FakePlatform)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def _post(self, path, body):
        return self.client.post(path, json=body)

    def test_check(self):
        r = self._post("/api/check", {"token": "t"})
        j = r.get_json()
        self.assertTrue(j["ok"])
        self.assertEqual(j["wallets"][0]["balance"], "100.00")

    def test_keys(self):
        r = self._post("/api/keys", {"token": "t"})
        j = r.get_json()
        self.assertEqual(len(j["keys"]), 2)

    def test_fetch(self):
        r = self._post("/api/fetch", {"token": "t", "start": "2026-07-01", "end": "2026-07-02",
                                      "tz": "28800", "granularity": "daily"})
        j = r.get_json()
        self.assertTrue(j["ok"])
        self.assertEqual(j["totals"]["requests"], 3)
        self.assertGreater(len(j["tables"]), 0)

    def test_export_job(self):
        r = self._post("/api/export", {"token": "t", "start": "2026-07-01", "end": "2026-07-02",
                                       "tz": "28800", "granularity": "daily",
                                       "formats": ["xlsx", "csv"], "include_raw": True})
        j = r.get_json()
        self.assertTrue(j["ok"])
        job_id = j["job_id"]
        # 等待任务完成
        import time
        for _ in range(100):
            rr = self.client.get(f"/api/job/{job_id}")
            jj = rr.get_json()
            if jj["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        self.assertEqual(jj["status"], "done", jj.get("error"))
        names = {f["name"] for f in jj["files"]}
        self.assertIn("usage.xlsx", names)
        self.assertTrue(any(n.startswith("raw_") for n in names))
        # 文件可下载
        f0 = jj["files"][0]
        dl = self.client.get(f0["url"])
        self.assertEqual(dl.status_code, 200, dl.data[:200])
        self.assertGreater(len(dl.data), 0)
        dl.close()

    def test_download_path_guard(self):
        r = self.client.get("/api/download", query_string={"f": "C:/Windows/win.ini"})
        self.assertEqual(r.status_code, 400)


class TestCliIntegration(unittest.TestCase):
    def test_range_export(self):
        from dsusage import cli
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "exports"
            with mock.patch("dsusage.cli.DeepSeekPlatformClient", FakePlatform), \
                 mock.patch.dict(os.environ, {"DSU_CONFIG_DIR": tmp}):
                code = cli.main(["range", "--start", "2026-07-01", "--end", "2026-07-02",
                                 "--granularity", "daily", "--format", "both",
                                 "--out", str(out_dir), "--token", "t"])
            self.assertEqual(code, 0)
            subdirs = list(out_dir.iterdir())
            self.assertEqual(len(subdirs), 1)
            files = {p.name for p in subdirs[0].iterdir()}
            self.assertIn("usage.xlsx", files)
            self.assertIn("daily_summary.csv", files)
            self.assertIn("model_summary.csv", files)
            self.assertIn("meta.json", files)
            meta = json.loads((subdirs[0] / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["start_date"], "2026-07-01")
            self.assertEqual(meta["totals"]["total_tokens"], 43)

    def test_login_and_logout(self):
        from dsusage import cli
        from dsusage.config import load_token
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("dsusage.cli.DeepSeekPlatformClient", FakePlatform), \
                 mock.patch.dict(os.environ, {"DSU_CONFIG_DIR": tmp}):
                code = cli.main(["login", "--token", "abc123"])
                self.assertEqual(code, 0)
                self.assertEqual(load_token(), "abc123")
                code = cli.main(["logout"])
                self.assertEqual(code, 0)
                self.assertIsNone(load_token())


if __name__ == "__main__":
    unittest.main()
