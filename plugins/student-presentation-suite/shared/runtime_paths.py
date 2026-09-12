"""Runtime path discovery for the Claude Code plugin."""

from __future__ import annotations

import os
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]

_MSYS_DRIVE = re.compile(r"[a-zA-Z]")


def _normalize_platform_path(value: str) -> Path:
    """容忍 MSYS/Git-Bash 风格的 ``/e/foo`` 盘符省略路径。

    Claude 宿主环境可能把 ``CLAUDE_PROJECT_DIR`` 写成 Git-Bash 形式（``/e/...``）。
    Windows 上 ``Path('/e/foo').resolve()`` 会错误拼接到"当前盘符"，得到
    ``E:/e/foo``。首段为单个字母（盘符样式）时按 MSYS 约定转换成 ``X:\\foo``；
    ``/tmp``、``/usr`` 这类非盘符段不受影响。
    """
    candidate = Path(value).expanduser()
    if candidate.anchor == "\\" and not candidate.drive:
        parts = candidate.parts  # ('\\', 'e', 'foo')
        if len(parts) >= 2 and _MSYS_DRIVE.fullmatch(parts[1]):
            return Path(f"{parts[1].upper()}:\\").joinpath(*parts[2:])
    return candidate


def project_root(env: dict[str, str] | None = None, cwd: Path | None = None) -> Path:
    # 注意必须用 `is not None` 判断：调用方传空 dict 表示"明确无环境变量"，
    # `env or os.environ` 会把空 dict 当假值回退到真实进程环境，导致
    # CLAUDE_PROJECT_DIR 泄漏进测试与子命令（tests/test_runtime_paths.py 回归过）。
    values = env if env is not None else os.environ
    configured = values.get("CLAUDE_PROJECT_DIR")
    if configured:
        resolved = _normalize_platform_path(configured).resolve()
        # 安全防护：拒绝路径穿越尝试
        if ".." in configured.replace("/", os.sep).split(os.sep):
            raise ValueError(
                f"CLAUDE_PROJECT_DIR 包含 '..' 路径穿越: {configured}"
            )
        return resolved
    return (cwd or Path.cwd()).resolve()


def output_root(
    requested: Path | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> Path:
    if requested:
        return requested.expanduser().resolve()
    return project_root(env=env, cwd=cwd) / "outputs"


def get_pptx_runtime_root() -> Path:
    """返回 suite-owned PPTX runtime package 路径。"""
    return PLUGIN_ROOT / "shared" / "pptx_runtime"
