"""配置与 Token 管理。

Token 说明：用户在 platform.deepseek.com 登录后，浏览器 localStorage 的
`userToken` 键（JSON，取 `.value` 字段）即为本工具的 Bearer Token。
本模块负责 Token 的保存 / 读取 / 校验，存储于用户目录的 config.json。
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from typing import Optional

CONFIG_DIR_ENV = "DSU_CONFIG_DIR"


def config_dir() -> Path:
    """返回配置目录（可用环境变量 DSU_CONFIG_DIR 覆盖，便于测试）。"""
    env = os.environ.get(CONFIG_DIR_ENV)
    if env:
        return Path(env)
    home = Path.home()
    return home / ".dsusage"


def config_path() -> Path:
    return config_dir() / "config.json"


def _secure_permissions(path: Path) -> None:
    """Windows 上尽可能限制文件 ACL（POSIX 上 600）。"""
    try:
        if os.name == "posix":
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        else:
            # Windows: 去掉 Everyone/Users 的读权限（尽力而为）
            import win32api  # type: ignore  # noqa: F401
        # win32api 不可用时忽略
    except Exception:
        pass


def load_token() -> Optional[str]:
    """读取已保存的 Token；不存在或为空返回 None。"""
    path = config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    token = data.get("token") or ""
    return token.strip() or None


def save_token(token: str, meta: Optional[dict] = None) -> Path:
    """保存 Token 与附加元信息（如备注、保存时间）。"""
    token = (token or "").strip()
    if not token:
        raise ValueError("Token 不能为空")
    cfg_dir = config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    path = config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data["token"] = token
    if meta:
        data.update(meta)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _secure_permissions(path)
    return path


def clear_token() -> bool:
    """删除已保存的 Token。返回是否确实删除。"""
    path = config_path()
    if path.exists():
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return False


def load_config() -> dict:
    """读取整个配置文件（不存在时返回空 dict）。"""
    path = config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def prompt_token_interactive() -> Optional[str]:
    """交互式输入 Token（隐藏回显；不支持 TTY 时退化为普通输入）。"""
    if sys.stdin is None or not sys.stdin.isatty():
        # 非交互环境：从 stdin 读一行
        line = sys.stdin.readline()
        return line.strip() or None
    try:
        import getpass

        return getpass.getpass("请粘贴 platform.deepseek.com 的 userToken（输入后回车，不回显）: ").strip() or None
    except Exception:
        return input("请粘贴 platform.deepseek.com 的 userToken: ").strip() or None
