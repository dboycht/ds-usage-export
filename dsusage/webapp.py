"""本地 Web 界面（Flask）：查询预览 + 一键导出。默认仅绑定 127.0.0.1。"""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from flask import Flask, jsonify, request, send_file

from . import __version__
from .aggregate import build_tables, compute_totals
from .api import (ApiError, AuthError, DeepSeekPlatformClient, parse_tz,
                  tz_label)
from .config import load_token, save_token
from .exporters import size_human
from .service import Service

STATIC_DIR = Path(__file__).parent / "web" / "static"

DEFAULT_EXPORTS_DIR = Path("exports")


# ---------------------------------------------------------------------------
# 后台任务
# ---------------------------------------------------------------------------

class JobManager:
    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, fn) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id, "status": "running", "logs": [],
                "result": None, "error": None, "started_at": datetime.now().isoformat(timespec="seconds"),
            }
        def _run():
            try:
                result = fn(self._log(job_id))
                with self._lock:
                    self._jobs[job_id].update(status="done", result=result,
                                              finished_at=datetime.now().isoformat(timespec="seconds"))
            except AuthError as e:
                with self._lock:
                    self._jobs[job_id].update(status="error", error=f"认证失败：{e}",
                                              finished_at=datetime.now().isoformat(timespec="seconds"))
            except ApiError as e:
                with self._lock:
                    self._jobs[job_id].update(status="error", error=f"平台错误：{e}",
                                              finished_at=datetime.now().isoformat(timespec="seconds"))
            except Exception as e:  # noqa: BLE001
                with self._lock:
                    self._jobs[job_id].update(status="error", error=f"导出失败：{e}",
                                              finished_at=datetime.now().isoformat(timespec="seconds"))
        threading.Thread(target=_run, daemon=True).start()
        return job_id

    def _log(self, job_id: str):
        def log(msg: str):
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job["logs"].append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        return log

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def prune(self, keep: int = 50) -> None:
        with self._lock:
            done = [j for j in self._jobs.values() if j["status"] != "running"]
            if len(done) > keep:
                drop = {j["id"] for j in done[:-keep]}
                self._jobs = {k: v for k, v in self._jobs.items() if k not in drop}


JOBS = JobManager()


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

def create_app(exports_dir: Path = DEFAULT_EXPORTS_DIR) -> Flask:
    app = Flask(__name__)
    exports_dir.mkdir(parents=True, exist_ok=True)

    from werkzeug.exceptions import HTTPException

    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException):
        """API 路由返回 JSON 错误；其他路由交回 Flask 默认页面（不再刷堆栈）。"""
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": e.description}), e.code
        return e

    @app.errorhandler(AuthError)
    def handle_auth_error(e: AuthError):
        return jsonify({"ok": False, "error": str(e)}), 401

    @app.errorhandler(ApiError)
    def handle_api_error(e: ApiError):
        return jsonify({"ok": False, "error": str(e)}), 502

    @app.errorhandler(Exception)
    def handle_other_error(e: Exception):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": f"内部错误: {e}"}), 500
        # 非 API 路径：返回简洁 500 页，避免在控制台打印堆栈
        return "Internal Server Error", 500

    @app.get("/favicon.ico")
    def favicon():
        # 浏览器会自动请求 favicon；返回 204 避免 404/500 刷屏
        return "", 204

    def _client_from_req() -> DeepSeekPlatformClient:
        data = request.get_json(force=True, silent=True) or {}
        token = (data.get("token") or "").strip() or load_token()
        if not token:
            raise AuthError("未提供 Token，请先在页面粘贴并验证")
        return DeepSeekPlatformClient(token)

    @app.get("/")
    def index():
        return send_file(STATIC_DIR / "index.html")

    @app.post("/api/check")
    def api_check():
        client = _client_from_req()
        summary = client.check()
        biz = summary if isinstance(summary, dict) else {}
        wallets = []
        for w in biz.get("normal_wallets", []):
            wallets.append({"currency": w.get("currency"), "balance": w.get("balance"),
                            "token_estimation": w.get("token_estimation")})
        bonuses = []
        for w in biz.get("bonus_wallets", []):
            bonuses.append({"currency": w.get("currency"), "balance": w.get("balance"),
                            "token_estimation": w.get("token_estimation")})
        return jsonify({"ok": True, "wallets": wallets, "bonus": bonuses,
                        "monthly_token_usage": biz.get("monthly_token_usage"),
                        "monthly_costs": biz.get("monthly_costs", [])})

    @app.post("/api/keys")
    def api_keys():
        client = _client_from_req()
        keys = client.get_api_keys()
        return jsonify({"ok": True, "keys": [
            {"trackingId": k.get("trackingId"), "name": k.get("name"),
             "sensitiveId": k.get("sensitiveId")} for k in keys]})

    @app.post("/api/fetch")
    def api_fetch():
        client = _client_from_req()
        data = request.get_json(force=True, silent=True) or {}
        start = date.fromisoformat(data["start"])
        end = date.fromisoformat(data["end"])
        tz_sec = parse_tz(data.get("tz", "local"))
        granularity = data.get("granularity", "auto")
        if granularity == "auto" and start == end:
            granularity = "hourly"
        api_key_ids = data.get("api_key_ids") or None
        ds = client.fetch_range(start, end, tz_sec, granularity, api_key_ids)
        tables = build_tables(ds)
        from .i18n import current_lang, tr_col
        lang = current_lang()
        preview = []
        for t in tables:
            cols = [tr_col(lang, c) for c in t.columns]
            preview.append({"name": t.name, "title": t.title,
                            "columns": cols,
                            "rows": [{col: r.get(old, "") for old, col in zip(t.columns, cols)}
                                     for r in t.rows[:100]]})
        return jsonify({"ok": True,
                        "totals": compute_totals(ds),
                        "granularity": ds.granularity(),
                        "bucket_sec": ds.bucket_sec,
                        "tables": preview,
                        "table_count": len(tables)})

    @app.post("/api/export")
    def api_export():
        client = _client_from_req()
        data = request.get_json(force=True, silent=True) or {}
        start = date.fromisoformat(data["start"])
        end = date.fromisoformat(data["end"])
        tz_sec = parse_tz(data.get("tz", "local"))
        granularity = data.get("granularity", "auto")
        if granularity == "auto" and start == end:
            granularity = "hourly"
        formats = data.get("formats") or ["xlsx"]
        include_raw = bool(data.get("include_raw"))
        api_key_ids = data.get("api_key_ids") or None
        out_dir_raw = data.get("out_dir")
        out_dir = Path(out_dir_raw) if out_dir_raw else exports_dir
        # 限制输出目录不越界（只允许 exports 目录或其子目录）
        try:
            out_dir.resolve().relative_to(exports_dir.resolve())
        except ValueError:
            return jsonify({"ok": False, "error": "非法输出目录"}), 400

        svc = Service(client)

        def run(log):
            return svc.run_export(start, end, tz_sec, granularity, formats,
                                  out_dir=out_dir, include_raw=include_raw,
                                  api_key_tracking_ids=api_key_ids, progress=log)

        job_id = JOBS.start(run)
        return jsonify({"ok": True, "job_id": job_id})

    @app.get("/api/job/<job_id>")
    def api_job(job_id: str):
        job = JOBS.get(job_id)
        if job is None:
            return jsonify({"ok": False, "error": "任务不存在"}), 404
        payload = {"ok": True, "status": job["status"], "logs": job["logs"],
                   "error": job["error"]}
        if job["result"]:
            res = job["result"]
            files = []
            for cat, names in res["files"].items():
                for n in names:
                    p = Path(res["out_dir"]) / n
                    files.append({"category": cat, "name": n,
                                  "path": str(p), "size": size_human(p.stat().st_size if p.exists() else 0),
                                  "url": f"/api/download?f={quote(str(p), safe='')}"})
            payload["files"] = files
            payload["out_dir"] = res["out_dir"]
            payload["totals"] = res["totals"]
            payload["meta"] = res["meta"]
        return jsonify(payload)

    @app.get("/api/exports")
    def api_exports():
        items = []
        for root in sorted(exports_dir.iterdir(), reverse=True):
            if not root.is_dir():
                continue
            files = []
            for f in sorted(root.iterdir()):
                if f.is_file():
                    files.append({"name": f.name, "size": size_human(f.stat().st_size),
                                  "url": f"/api/download?f={quote(str(f), safe='')}"})
            items.append({"dir": str(root), "files": files})
        return jsonify({"ok": True, "items": items[:20]})

    @app.get("/api/download")
    def api_download():
        f = request.args.get("f", "")
        path = Path(f)
        # 只允许 exports 目录内文件
        try:
            path.resolve().relative_to(exports_dir.resolve())
        except ValueError:
            return jsonify({"ok": False, "error": "非法路径"}), 400
        if not path.is_file():
            return jsonify({"ok": False, "error": "文件不存在"}), 404
        return send_file(path, as_attachment=True)

    @app.post("/api/save_token")
    def api_save_token():
        data = request.get_json(force=True, silent=True) or {}
        token = (data.get("token") or "").strip()
        if not token:
            return jsonify({"ok": False, "error": "Token 为空"}), 400
        try:
            save_token(token, {"saved_at": datetime.now().isoformat(timespec="seconds")})
            return jsonify({"ok": True})
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(e)}), 500

    return app


def run_server(host: str = "127.0.0.1", port: int = 8321, debug: bool = False) -> int:
    from .i18n import current_lang, tr
    app = create_app()
    lang = current_lang()
    print(f"{tr(lang, 'web_banner', ver=__version__)}")
    print(f"  {tr(lang, 'web_addr')} http://{host}:{port}")
    print(f"  {tr(lang, 'web_hint')}")
    app.run(host=host, port=port, debug=debug, threaded=True)
    return 0
