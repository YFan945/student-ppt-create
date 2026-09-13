#!/usr/bin/env python3
"""统一升级 student-presentation-suite 所有版本字段。"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*))?"
    r"(?:\+([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*))?$"
)


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE_ROOT = PLUGIN_ROOT.parents[1]  # 仓库根目录 (claude-plugins)

FILES_TO_UPDATE = [
    (
        MARKETPLACE_ROOT / ".claude-plugin" / "marketplace.json",
        "plugins[0].version",
        lambda data, ver: _update_plugin_entry(data, ver),
    ),
    (
        PLUGIN_ROOT / ".claude-plugin" / "plugin.json",
        "version",
        lambda data, ver: _set_key(data, "version", ver),
    ),
    (
        PLUGIN_ROOT / "package.json",
        "version",
        lambda data, ver: _set_key(data, "version", ver),
    ),
]
SKILL_FILES = sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))


def _set_key(data: dict, key: str, value: str) -> dict:
    data[key] = value
    return data


def _update_plugin_entry(data: dict, version: str) -> dict:
    plugins = data.get("plugins")
    if not plugins or not isinstance(plugins, list):
        raise ValueError("marketplace.json 中未找到 plugins 列表")
    if plugins[0].get("name") != "student-presentation-suite":
        raise ValueError("marketplace.json 第一个插件不是 student-presentation-suite")
    plugins[0]["version"] = version
    return data


def read_json(path: Path) -> dict:
    # utf-8-sig：容忍 Windows 工具写入的 BOM，避免 json.loads 首字符报错。
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def update_skill_version(path: Path, version: str, *, dry_run: bool = False) -> None:
    text = path.read_text(encoding="utf-8-sig")
    updated, count = re.subn(
        r"(?m)^version:\s*[^\r\n]+$",
        f"version: {version}",
        text,
        count=1,
    )
    if count != 1:
        raise ValueError(f"{path} 缺少唯一的 skill frontmatter version")
    if not dry_run:
        path.write_text(updated, encoding="utf-8")


def current_version() -> str:
    """从 plugin.json 读取当前版本。"""
    manifest = read_json(PLUGIN_ROOT / ".claude-plugin" / "plugin.json")
    return manifest.get("version", "0.0.0")


def _extract_version(data: dict, desc: str) -> str:
    if desc == "plugins[0].version":
        try:
            return data["plugins"][0]["version"]
        except (KeyError, IndexError, TypeError):
            return "?"
    return data.get("version", "?")


def bump(target: str, dry_run: bool = False) -> int:
    """更新所有版本字段并同步 lockfile。

    返回 0 表示成功，非 0 表示失败。
    """
    if not _SEMVER_RE.fullmatch(target):
        print(f"✗ 目标版本不是合法 semver: {target}", file=sys.stderr)
        return 1

    old_version = current_version()
    print(f"当前版本: {old_version} → {target}")

    # 先加载所有文件，避免中途失败留下半完成状态
    loaded: list[tuple[Path, str, Callable, dict]] = []
    for path, desc, updater in FILES_TO_UPDATE:
        try:
            data = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"✗ 无法读取 {path}: {exc}", file=sys.stderr)
            return 1
        loaded.append((path, desc, updater, data))

    if dry_run:
        for path, desc, updater, data in loaded:
            new_data = updater(data, target)
            print(f"  [dry-run] {path.name} {desc}: {_extract_version(new_data, desc)}")
        for path in SKILL_FILES:
            try:
                update_skill_version(path, target, dry_run=True)
            except (OSError, ValueError) as exc:
                print(f"✗ 无法检查 {path}: {exc}", file=sys.stderr)
                return 1
            print(f"  [dry-run] {path.parent.name}/SKILL.md version: {target}")
        print(f"\n[dry-run] 版本升级完成: {old_version} → {target}")
        return 0

    # 先写 package.json，再让 npm 同步 lockfile，最后写其余 JSON，确保 lockfile 版本一致
    package_item = next((item for item in loaded if item[0].name == "package.json"), None)
    if package_item is None:
        print("✗ 未找到 package.json", file=sys.stderr)
        return 1
    package_path, package_desc, package_updater, package_old = package_item
    package_new = package_updater(package_old, target)
    write_json(package_path, package_new)
    print(f"  ✓ {package_path.name} {package_desc}: {target}")

    def _revert_package() -> None:
        """npm 失败时回滚 package.json，避免半升级状态。"""
        with contextlib.suppress(OSError):
            write_json(package_path, package_old)

    print("  正在同步 package-lock.json ...")
    try:
        # 不用 shell=True：Windows 上列表参数经 cmd.exe 会分裂；npm 在 Windows
        # 实际是 npm.cmd，用 shutil.which 解析出可执行文件后直接调用。
        npm = shutil.which("npm")
        if npm is None:
            raise FileNotFoundError("npm not found on PATH")
        result = subprocess.run(
            [npm, "--prefix", str(PLUGIN_ROOT), "install", "--package-lock-only"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        _revert_package()
        print(f"✗ npm 调用失败: {exc}", file=sys.stderr)
        print("⚠ package.json 已回滚，请解决 npm 问题后重试。", file=sys.stderr)
        return 1
    if result.returncode != 0:
        _revert_package()
        print(f"✗ npm install --package-lock-only 失败: {result.stderr}", file=sys.stderr)
        print("⚠ package.json 已回滚，请解决 npm 问题后重试。", file=sys.stderr)
        return 1
    print("  ✓ package-lock.json 已同步")

    for path, desc, updater, data in loaded:
        if path.name == "package.json":
            continue
        updated = updater(data, target)
        write_json(path, updated)
        print(f"  ✓ {path.name} {desc}: {target}")
    for path in SKILL_FILES:
        try:
            update_skill_version(path, target)
        except (OSError, ValueError) as exc:
            print(f"✗ 无法更新 {path}: {exc}", file=sys.stderr)
            return 1
        print(f"  ✓ {path.parent.name}/SKILL.md version: {target}")

    print(f"\n版本升级完成: {old_version} → {target}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="统一升级 student-presentation-suite 所有版本字段"
    )
    parser.add_argument(
        "version",
        nargs="?",
        help="目标版本号，如 0.5.0。省略则仅显示当前版本。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览修改而不实际写入文件",
    )
    args = parser.parse_args()

    if not args.version:
        print(f"当前版本: {current_version()}")
        return

    raise SystemExit(bump(args.version, args.dry_run))


if __name__ == "__main__":
    main()
