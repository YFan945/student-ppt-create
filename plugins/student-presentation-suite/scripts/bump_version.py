#!/usr/bin/env python3
"""统一升级 student-presentation-suite 所有版本字段。"""

from __future__ import annotations

import argparse
import copy
import json
import re
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
LOCKFILE = PLUGIN_ROOT / "package-lock.json"


def _set_key(data: dict, key: str, value: str) -> dict:
    """返回设置了 ``key`` 的副本。

    **不得原地修改传入的 dict**：``bump()`` 会保留升级前的对象用于回滚，原地更新
    会让回滚把已经升级过的值原样写回去，变成静默的空操作。
    """
    updated = copy.deepcopy(data)
    updated[key] = value
    return updated


def _update_plugin_entry(data: dict, version: str) -> dict:
    plugins = data.get("plugins")
    if not plugins or not isinstance(plugins, list):
        raise ValueError("marketplace.json 中未找到 plugins 列表")
    if plugins[0].get("name") != "student-presentation-suite":
        raise ValueError("marketplace.json 第一个插件不是 student-presentation-suite")
    updated = copy.deepcopy(data)
    updated["plugins"][0]["version"] = version
    return updated


def read_json(path: Path) -> dict:
    # utf-8-sig：容忍 Windows 工具写入的 BOM，避免 json.loads 首字符报错。
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sync_package_lock(version: str, *, dry_run: bool = False) -> str:
    """把 package-lock.json 的版本字段对齐，不经过 npm。

    对一次纯粹的版本升级而言，``npm install --package-lock-only`` 只会改写
    lockfile 的 ``version`` 与 ``packages[""].version`` 两个字段。改为直接改这两处
    有两点好处：结果是确定的、可离线复现；并且不再依赖调用方的工作目录——早先的
    实现用 ``npm --prefix``，实测 npm 仍按 cwd 解析，导致在仓库根目录运行时整个
    升级失败。

    返回 ``updated`` / ``unchanged`` / ``missing``。
    """
    if not LOCKFILE.is_file():
        return "missing"
    try:
        data = read_json(LOCKFILE)
    except (OSError, json.JSONDecodeError):
        return "missing"
    changed = False
    if data.get("version") != version:
        data["version"] = version
        changed = True
    root_package = (data.get("packages") or {}).get("")
    if isinstance(root_package, dict) and root_package.get("version") != version:
        root_package["version"] = version
        changed = True
    if changed and not dry_run:
        write_json(LOCKFILE, data)
    return "updated" if changed else "unchanged"


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

    # 先加载并校验所有文件，避免中途失败留下半完成状态
    loaded: list[tuple[Path, str, Callable, dict]] = []
    for path, desc, updater in FILES_TO_UPDATE:
        try:
            data = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"✗ 无法读取 {path}: {exc}", file=sys.stderr)
            return 1
        try:
            updater(data, target)
        except ValueError as exc:
            print(f"✗ {path}: {exc}", file=sys.stderr)
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
        print(f"  [dry-run] package-lock.json: {sync_package_lock(target, dry_run=True)}")
        print(f"\n[dry-run] 版本升级完成: {old_version} → {target}")
        return 0

    lock_state = sync_package_lock(target)
    print(f"  ✓ package-lock.json: {lock_state}")

    for path, desc, updater, data in loaded:
        write_json(path, updater(data, target))
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
