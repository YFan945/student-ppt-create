#!/usr/bin/env python3
"""Check source and live Claude Code plugin version consistency."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ID = "student-presentation-suite@claude-personal"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def source_versions(root: Path = ROOT) -> dict[str, str | None]:
    plugin = root / "plugins" / "student-presentation-suite"
    lock = read_json(plugin / "package-lock.json")
    return {
        "marketplace": read_json(root / ".claude-plugin" / "marketplace.json")["plugins"][0].get("version"),
        "manifest": read_json(plugin / ".claude-plugin" / "plugin.json").get("version"),
        "package": read_json(plugin / "package.json").get("version"),
        "package_lock": lock.get("version"),
        "package_lock_root": (lock.get("packages") or {}).get("", {}).get("version"),
    }


def parse_list_version(text: str, plugin_id: str = PLUGIN_ID) -> str | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if plugin_id in line:
            for following in lines[index + 1:index + 5]:
                match = re.search(r"\bVersion:\s*([^\s]+)", following)
                if match:
                    return match.group(1)
    return None


def parse_details_version(text: str) -> str | None:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    match = re.search(r"\bstudent-presentation-suite\s+([^\s]+)", first)
    return match.group(1) if match else None


def command_output(*args: str) -> str:
    executable = shutil.which(args[0]) or args[0]
    if os.name == "nt" and not PurePath(executable).suffix:
        command_shim = shutil.which(f"{args[0]}.cmd")
        if command_shim:
            executable = command_shim
    command: tuple[str, ...]
    if PurePath(executable).suffix.lower() in {".cmd", ".bat"}:
        command = (
            os.environ.get("ComSpec", "cmd.exe"),
            "/d",
            "/s",
            "/c",
            executable,
            *args[1:],
        )
    else:
        command = (executable, *args[1:])
    proc = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "command failed").strip())
    return proc.stdout


def inspect(source_only: bool = False) -> dict[str, Any]:
    sources = source_versions()
    expected = sources["manifest"]
    errors = [
        f"source version mismatch: {name}={version!r}, expected={expected!r}"
        for name, version in sources.items()
        if version != expected
    ]
    live: dict[str, str | None] = {}
    if not source_only:
        try:
            live["plugin_list"] = parse_list_version(command_output("claude", "plugin", "list"))
            live["plugin_details"] = parse_details_version(
                command_output("claude", "plugin", "details", PLUGIN_ID)
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            errors.append(f"cannot inspect Claude plugin state: {exc}")
        for name, version in live.items():
            if version != expected:
                errors.append(f"live version mismatch: {name}={version!r}, expected={expected!r}")
    return {
        "ok": not errors,
        "expected": expected,
        "source_versions": sources,
        "live_versions": live,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Claude plugin version consistency")
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = inspect(args.source_only)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"]:
        print(f"Version consistency passed: {result['expected']}")
    else:
        for error in result["errors"]:
            print(f"- {error}")
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
