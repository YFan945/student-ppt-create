#!/usr/bin/env python3
"""Validate the Claude Code-only marketplace release."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*))?"
    r"(?:\+([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*))?$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Claude Code marketplace structure")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    return parser.parse_args()


def git_output(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "git failed").strip())
    return proc.stdout.strip()


def load_json(path: Path) -> dict:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"UTF-8 BOM is not allowed: {path.relative_to(ROOT)}")
    return json.loads(raw.decode("utf-8"))


def release_branch_error(
    local_branch: str,
    head_ref: str,
    base_ref: str,
    ref_name: str,
) -> str | None:
    if head_ref:
        if base_ref != "main":
            return (
                "Claude marketplace pull requests must target main, "
                f"got {base_ref!r}"
            )
        return None
    branch = local_branch or ref_name
    if branch != "main":
        return f"Claude marketplace must be released from main, got {branch!r}"
    return None


def main() -> None:
    args = parse_args()
    errors: list[str] = []
    required = [
        ".claude-plugin/marketplace.json",
        "README.md",
        "README-zh.md",
        "CHANGELOG.md",
        ".github/workflows/validate.yml",
        "scripts/install_claude_plugin.ps1",
        "scripts/check_installed_version.py",
    ]
    for rel in required:
        if not (ROOT / rel).is_file():
            errors.append(f"Missing required file: {rel}")

    try:
        branch_error = release_branch_error(
            git_output("branch", "--show-current"),
            os.environ.get("GITHUB_HEAD_REF", ""),
            os.environ.get("GITHUB_BASE_REF", ""),
            os.environ.get("GITHUB_REF_NAME", ""),
        )
        if branch_error:
            errors.append(branch_error)
        tracked = git_output("ls-files").splitlines()
        folded: dict[str, str] = {}
        for rel in tracked:
            key = rel.casefold()
            if key in folded and folded[key] != rel:
                errors.append(f"Case-colliding tracked paths: {folded[key]} and {rel}")
            folded[key] = rel
    except RuntimeError as exc:
        errors.append(f"Cannot inspect Git release state: {exc}")

    try:
        marketplace = load_json(ROOT / ".claude-plugin/marketplace.json")
        if marketplace.get("name") != "claude-personal":
            errors.append("Claude marketplace name must be claude-personal")
        plugins = marketplace.get("plugins")
        if not isinstance(plugins, list) or not plugins:
            errors.append("Claude marketplace must contain at least one plugin")
            plugins = []
        names: set[str] = set()
        for index, entry in enumerate(plugins):
            name = entry.get("name")
            if not name or name in names:
                errors.append(f"Marketplace plugin entry {index} has a missing or duplicate name")
                continue
            names.add(name)
            source = entry.get("source")
            if not isinstance(source, str) or not source.startswith("./plugins/"):
                errors.append(f"{name}: source must be a ./plugins/ path")
                continue
            plugin_root = (ROOT / source).resolve()
            try:
                plugin_root.relative_to(ROOT.resolve())
            except ValueError:
                errors.append(f"{name}: source escapes marketplace root")
                continue
            manifest = load_json(plugin_root / ".claude-plugin/plugin.json")
            if manifest.get("name") != name:
                errors.append(f"{name}: marketplace and manifest names differ")
            if manifest.get("version") != entry.get("version"):
                errors.append(f"{name}: marketplace and manifest versions differ")
            package = load_json(plugin_root / "package.json")
            lock = load_json(plugin_root / "package-lock.json")
            versions = {
                "marketplace": entry.get("version"),
                "manifest": manifest.get("version"),
                "package": package.get("version"),
                "package-lock": lock.get("version"),
                "package-lock root": (lock.get("packages") or {}).get("", {}).get("version"),
            }
            if any(ver is None for ver in versions.values()):
                errors.append(f"{name}: one or more version fields are missing")
                continue
            for source, ver in versions.items():
                if not _SEMVER_RE.fullmatch(ver):
                    errors.append(f"{name}: {source} version is not valid semver: {ver}")
            if len(set(versions.values())) != 1:
                errors.append(f"{name}: synchronized versions differ: {versions}")
            expected_version = entry.get("version")
            for skill_file in sorted((plugin_root / "skills").glob("*/SKILL.md")):
                skill_text = skill_file.read_text(encoding="utf-8")
                match = re.search(r"(?m)^version:\s*(\S+)\s*$", skill_text)
                if not match:
                    errors.append(
                        f"{name}: {skill_file.relative_to(plugin_root)} missing frontmatter version"
                    )
                elif match.group(1) != expected_version:
                    errors.append(
                        f"{name}: {skill_file.relative_to(plugin_root)} version "
                        f"{match.group(1)!r} differs from release {expected_version!r}"
                    )
            for field in ("homepage", "repository", "license", "keywords"):
                if not entry.get(field):
                    errors.append(f"{name}: marketplace entry missing metadata {field}")
            if (plugin_root / ".codex-plugin").exists():
                errors.append(f"{name}: Claude plugin must not contain .codex-plugin")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        errors.append(f"Cannot validate Claude marketplace: {exc}")

    result = {"ok": not errors, "error_count": len(errors), "errors": errors}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("Claude marketplace release check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print("Claude marketplace release check passed.")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
