"""可选：从本地 Chrome 配置自动读取 userToken（需要 playwright）。

用法：
    python -m dsusage.browser_token            # 打印 token 到 stdout
    python -m dsusage.browser_token --save     # 同时保存到本机配置

注意：读取的是 Chrome 用户配置，请先关闭 Chrome，或使用独立配置目录运行。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _find_chrome_profile() -> Path | None:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data" / "Default",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Chromium" / "User Data" / "Default",
        Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "User Data" / "Default",
        Path.home() / ".config" / "google-chrome" / "Default",
        Path.home() / ".config" / "chromium" / "Default",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    return None


def extract_token() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("未安装 playwright：pip install playwright && playwright install chromium", file=sys.stderr)
        return None
    profile = _find_chrome_profile()
    if not profile:
        print("未找到 Chrome/Chromium 用户配置目录", file=sys.stderr)
        return None
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(profile), headless=True, channel="chrome",
                args=["--no-sandbox", "--disable-gpu"],
            )
            page = ctx.new_page()
            page.goto("https://platform.deepseek.com/usage",
                      wait_until="domcontentloaded", timeout=20000)
            token = page.evaluate(
                "() => { try { return JSON.parse(localStorage.getItem('userToken')).value; }"
                " catch (e) { return null; } }"
            )
            ctx.close()
            return token
    except Exception as e:  # noqa: BLE001
        print(f"提取失败：{e}", file=sys.stderr)
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="从 Chrome 配置提取 platform.deepseek.com userToken")
    ap.add_argument("--save", action="store_true", help="同时保存到本机配置")
    args = ap.parse_args(argv)
    token = extract_token()
    if not token:
        print("未能提取 Token，请改用「方式一：控制台复制」（见 docs/获取Token.md）", file=sys.stderr)
        return 1
    if args.save:
        from .config import save_token
        save_token(token)
        print("Token 已保存到本机配置。")
    else:
        print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
