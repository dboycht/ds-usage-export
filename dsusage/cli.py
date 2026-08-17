"""命令行入口（dsu）。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from . import __version__
from .api import (ApiError, AuthError, DeepSeekPlatformClient, parse_tz,
                  tz_label)
from .config import (clear_token, load_config, load_token,
                     prompt_token_interactive, save_token)
from .i18n import current_lang, detect_lang, set_lang, tr
from .service import Service

EPILOG = """Examples / 示例:
  dsu login                          # save userToken
  dsu check                          # verify token & show balance
  dsu keys                           # list API keys (trackingId / name)
  dsu day --date 2026-07-01          # single-day hourly usage (xlsx+csv+html)
  dsu go --start 2026-06-01 --end 2026-06-30           # one-click export + open report
  dsu go --start 2026-01-01 --end 2026-12-31 --granularity daily   # full year
  dsu range --start 2026-06-01 --end 2026-06-30 --granularity hourly --open
  dsu serve --port 8321              # start local web UI
  dsu --lang en ...                  # force English interface
"""


def _client(args) -> DeepSeekPlatformClient:
    token = getattr(args, "token", None) or load_token()
    return DeepSeekPlatformClient(token)


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date, expected YYYY-MM-DD: {s!r}")


def cmd_login(args) -> int:
    token = args.token
    if not token:
        token = prompt_token_interactive()
    if not token:
        print(tr(current_lang(), "token_cancel"), file=sys.stderr)
        return 1
    client = DeepSeekPlatformClient(token)
    try:
        summary = client.check()
    except AuthError as e:
        print(f"{tr(current_lang(), 'auth_failed')}{e}", file=sys.stderr)
        return 1
    save_token(token, {"saved_at": datetime.now().isoformat(timespec="seconds")})
    print(tr(current_lang(), "token_saved"), _cfg_path())
    print_summary(summary)
    return 0


def cmd_check(args) -> int:
    client = _client(args)
    try:
        summary = client.check()
    except AuthError as e:
        print(f"{tr(current_lang(), 'auth_failed')}{e}", file=sys.stderr)
        print(tr(current_lang(), "login_again"), file=sys.stderr)
        return 1
    print(tr(current_lang(), "token_valid"))
    print_summary(summary)
    return 0


def print_summary(summary) -> None:
    """打印用户摘要（余额、本月用量）。"""
    lang = current_lang()
    biz = summary if isinstance(summary, dict) else {}
    if isinstance(biz, dict) and "normal_wallets" in biz:
        for w in biz.get("normal_wallets", []):
            print(f"  {tr(lang, 'balance')}[{w.get('currency')}]: {w.get('balance')}")
        for w in biz.get("bonus_wallets", []):
            print(f"  {tr(lang, 'bonus_balance')}[{w.get('currency')}]: {w.get('balance')}")
        if biz.get("monthly_token_usage") is not None:
            print(f"  {tr(lang, 'monthly_tokens')}: {biz.get('monthly_token_usage')}")
        for c in biz.get("monthly_costs", []):
            print(f"  {tr(lang, 'monthly_cost')}[{c.get('currency')}]: {c.get('amount')}")
    else:
        print("  ", json.dumps(biz, ensure_ascii=False)[:400])


def cmd_keys(args) -> int:
    client = _client(args)
    try:
        keys = client.get_api_keys()
    except AuthError as e:
        print(f"{tr(current_lang(), 'auth_failed')}{e}", file=sys.stderr)
        return 1
    if not keys:
        print(tr(current_lang(), "no_api_keys"))
        return 0
    name_h = "名称" if current_lang() == "zh" else "Name"
    print(f"{'trackingId':<40} {name_h:<24} 敏感ID/SensitiveID")
    for k in keys:
        print(f"{k.get('trackingId') or '':<40} {(k.get('name') or '')[:24]:<24} {k.get('sensitiveId') or ''}")
    print(f"\n{tr(current_lang(), 'keys_count', n=len(keys))}")
    return 0


def _run_query(args) -> int:
    client = _client(args)
    svc = Service(client)
    lang = current_lang()
    start = args.start
    end = args.end
    tz_sec = parse_tz(args.tz)
    granularity = args.granularity
    if args.granularity == "auto" and start == end:
        granularity = "hourly"   # 单日默认小时级
    formats = {"xlsx": ["xlsx"], "csv": ["csv"], "html": ["html"],
               "both": ["xlsx", "csv"], "all": ["xlsx", "csv", "html"]}.get(
        args.format, ["xlsx", "csv", "html"])
    api_key_ids = args.api_key.split(",") if args.api_key else None
    try:
        result = svc.run_export(
            start, end, tz_sec, granularity, formats,
            out_dir=Path(args.out) if args.out else None,
            include_raw=args.include_raw,
            api_key_tracking_ids=api_key_ids,
            progress=lambda m: print("  ·", m, file=sys.stderr),
        )
    except AuthError as e:
        print(f"{tr(lang, 'auth_failed')}{e}", file=sys.stderr)
        return 1
    except ApiError as e:
        print(f"{tr(lang, 'fetch_failed')}{e}", file=sys.stderr)
        return 1

    totals = result["totals"]
    if args.granularity == "hourly" and totals["granularity"] != "hourly":
        print(tr(lang, "warn_granularity"), file=sys.stderr)
    print(f"\n{tr(lang, 'export_done')} {result['out_dir']}")
    print(f"  {tr(lang, 'period')}: {start} ~ {end}  {tr(lang, 'timezone')}: {tz_label(tz_sec)}  "
          f"{tr(lang, 'granularity')}: {totals['granularity']}")
    print(f"  {tr(lang, 'requests')}: {totals['requests']:,}  {tr(lang, 'cache_hit')}: {totals['cache_hit']:,}  "
          f"{tr(lang, 'cache_miss')}: {totals['cache_miss']:,}  {tr(lang, 'output')}: {totals['response']:,}")
    print(f"  {tr(lang, 'tokens_total')}: {totals['total_tokens']:,}  {tr(lang, 'cost_total')}: {totals['cost']:.6f}")
    for cat in ("xlsx", "csv", "html", "raw", "meta"):
        if result["files"].get(cat):
            for f in result["files"][cat]:
                print(f"  [{cat}] {f}")
    if getattr(args, "open", False) and "html" in result["files"]:
        import webbrowser
        report = str(Path(result["out_dir"]) / result["files"]["html"][0])
        print(f"  {tr(lang, 'opening_report')} {report}")
        webbrowser.open("file:///" + report.replace("\\", "/").replace(" ", "%20"))
    return 0


def cmd_day(args) -> int:
    args.start = args.end = args.date
    if args.granularity == "auto":
        args.granularity = "hourly"
    return _run_query(args)


def cmd_go(args) -> int:
    """一键导出：全部格式 + 官方原始数据 + 自动打开 HTML 报告。"""
    args.format = "all"
    args.include_raw = True
    args.open = True
    return _run_query(args)


def cmd_serve(args) -> int:
    try:
        from .webapp import run_server
    except ImportError as e:
        print(tr(current_lang(), "web_needs_flask", e=e), file=sys.stderr)
        return 1
    return run_server(args.host, args.port, debug=args.debug)


def cmd_logout(args) -> int:
    if clear_token():
        print(tr(current_lang(), "token_cleared"))
    else:
        print(tr(current_lang(), "no_saved_token"))
    return 0


def cmd_diagnose(args) -> int:
    """抓取原始 amount/cost 响应并保存，用于排查平台数据结构。"""
    import json as _json
    from pathlib import Path as _Path
    from .api import start_end_sec, tz_label
    from .i18n import current_lang as _cur, tr as _tr

    client = _client(args)
    out_dir = _Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tz_sec = parse_tz(args.tz)
    s0, e0 = start_end_sec(args.date, args.date, tz_sec)
    print(_tr(_cur(), "diagnose_title", d=args.date, s=s0, e=e0, tz=tz_label(tz_sec)))
    try:
        amount_biz = client.get_usage_amount(s0, e0, tz_sec)
        cost_biz = client.get_usage_cost(s0, e0, tz_sec)
    except ApiError as e:
        print(f"{_tr(_cur(), 'fetch_failed')}{e}", file=sys.stderr)
        return 1

    def _shape(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                t = type(v).__name__
                if isinstance(v, list):
                    t = f"list[{len(v)}]"
                    if v and isinstance(v[0], dict):
                        t += " of " + ",".join(v[0].keys())
                print(f"  {prefix}{k}: {t}")
        elif isinstance(obj, list):
            print(f"  {prefix}[list {len(obj)}]")
            if obj:
                _shape(obj[0], prefix + "  [0].")
        else:
            print(f"  {prefix}{type(obj).__name__}")

    for name, biz in (("amount", amount_biz), ("cost", cost_biz)):
        path = out_dir / f"diagnose_{name}_{args.date}.json"
        path.write_text(_json.dumps(biz, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n=== {name} ===")
        _shape(biz)

        def _first_api_key(obj):
            if isinstance(obj, dict):
                for s in obj.get("series") or []:
                    if isinstance(s, dict) and "api_key" in s:
                        return s["api_key"]
                for d in obj.get("data") or []:
                    if isinstance(d, dict):
                        for s in d.get("series") or []:
                            if isinstance(s, dict) and "api_key" in s:
                                return s["api_key"]
            return None
        ak = _first_api_key(biz)
        if ak is not None:
            if isinstance(ak, dict):
                print(f"  {_tr(_cur(), 'diagnose_api_key_dict', keys=list(ak.keys()))}")
            else:
                print(f"  {_tr(_cur(), 'diagnose_api_key_type', t=type(ak).__name__, v=str(ak)[:60])}")
        print(f"  bucket: {biz.get('bucket') if isinstance(biz, dict) else '?'}")
    print(f"\n{_tr(_cur(), 'diagnose_dir')} {out_dir.resolve()}")
    print(_tr(_cur(), "diagnose_hint"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dsu",
        description=f"DeepSeek 用量导出工具 v{__version__} / DeepSeek Usage Export v{__version__}",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-v", "--version", action="version", version=__version__)
    p.add_argument("--lang", choices=["zh", "en"], default=None,
                   help="界面语言 / interface language (默认自动检测)")
    sub = p.add_subparsers(dest="cmd")

    def add_common(sp):
        sp.add_argument("--token", help="直接指定 userToken（不读取已保存的配置）")

    sp = sub.add_parser("login", help="保存 userToken（登录态）/ save userToken")
    sp.add_argument("--token", help="直接粘贴 token（否则交互输入）")
    sp.set_defaults(func=cmd_login)

    sp = sub.add_parser("check", help="校验 Token 并显示账户信息")
    add_common(sp)
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("keys", help="列出 API Key")
    add_common(sp)
    sp.set_defaults(func=cmd_keys)

    sp = sub.add_parser("day", help="单日小时级用量导出（默认含报纸风 HTML 图表报告）")
    add_common(sp)
    sp.add_argument("--date", required=True, type=_parse_date, help="日期 YYYY-MM-DD")
    sp.add_argument("--tz", default="local", help="时区（+08:00 / 28800 / 8.0 / local）")
    sp.add_argument("--granularity", choices=["auto", "hourly", "daily"], default="auto")
    sp.add_argument("--format", choices=["xlsx", "csv", "html", "both", "all"], default="all",
                    help="all = xlsx + csv + html 报告（默认）")
    sp.add_argument("--out", help="输出目录（默认 ./exports）")
    sp.add_argument("--include-raw", action="store_true", help="同时下载官方原始导出 CSV")
    sp.add_argument("--open", action="store_true", help="导出后用浏览器打开 HTML 报告")
    sp.add_argument("--api-key", help="仅导出指定 trackingId（逗号分隔多个）")
    sp.set_defaults(func=cmd_day)

    sp = sub.add_parser("range", help="日期范围导出（超 30 天自动分片，默认含 HTML 报告）")
    add_common(sp)
    sp.add_argument("--start", required=True, type=_parse_date, help="开始日期 YYYY-MM-DD")
    sp.add_argument("--end", required=True, type=_parse_date, help="结束日期 YYYY-MM-DD")
    sp.add_argument("--tz", default="local", help="时区（+08:00 / 28800 / 8.0 / local）")
    sp.add_argument("--granularity", choices=["auto", "hourly", "daily"], default="auto",
                    help="auto=按服务端粒度；hourly=逐日强制小时桶；daily=按天聚合")
    sp.add_argument("--format", choices=["xlsx", "csv", "html", "both", "all"], default="all",
                    help="all = xlsx + csv + html 报告（默认）")
    sp.add_argument("--out", help="输出目录（默认 ./exports）")
    sp.add_argument("--include-raw", action="store_true", help="同时下载官方原始导出 CSV")
    sp.add_argument("--open", action="store_true", help="导出后用浏览器打开 HTML 报告")
    sp.add_argument("--api-key", help="仅导出指定 trackingId（逗号分隔多个）")
    sp.set_defaults(func=_run_query)

    sp = sub.add_parser("go", help="一键导出：全部格式 + 官方原始数据 + 自动打开 HTML 报告")
    add_common(sp)
    sp.add_argument("--start", required=True, type=_parse_date, help="开始日期 YYYY-MM-DD")
    sp.add_argument("--end", required=True, type=_parse_date, help="结束日期 YYYY-MM-DD")
    sp.add_argument("--tz", default="local", help="时区（+08:00 / 28800 / 8.0 / local）")
    sp.add_argument("--granularity", choices=["auto", "hourly", "daily"], default="auto")
    sp.add_argument("--out", help="输出目录（默认 ./exports）")
    sp.add_argument("--api-key", help="仅导出指定 trackingId（逗号分隔多个）")
    sp.set_defaults(func=cmd_go)

    sp = sub.add_parser("serve", help="启动本地 Web 界面")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8321)
    sp.add_argument("--debug", action="store_true")
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("diagnose", help="抓取原始响应排查平台数据结构")
    add_common(sp)
    sp.add_argument("--date", type=_parse_date, default=date.today(), help="日期 YYYY-MM-DD（默认今天）")
    sp.add_argument("--tz", default="local", help="时区（+08:00 / 28800 / 8.0 / local）")
    sp.add_argument("--out", default="diagnose", help="输出目录（默认 ./diagnose）")
    sp.set_defaults(func=cmd_diagnose)

    sp = sub.add_parser("logout", help="清除本地保存的 Token")
    sp.set_defaults(func=cmd_logout)

    return p


def _setup_console() -> None:
    """Windows 控制台以 UTF-8 输出中文。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass


def main(argv: Optional[List[str]] = None) -> int:
    _setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    # 语言解析：--lang > 配置文件 > 环境变量/系统 locale
    set_lang(args.lang or detect_lang(load_config().get("lang")))
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args) or 0
    except KeyboardInterrupt:
        print("\nInterrupted / 已取消。", file=sys.stderr)
        return 130


def _cfg_path() -> Path:
    from .config import config_path
    return config_path()


if __name__ == "__main__":
    sys.exit(main())
