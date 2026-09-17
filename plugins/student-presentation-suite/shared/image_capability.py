"""Whether this session can actually obtain imagery — one owner for one fact.

The declaration contract lives in `references/image-sourcing.md`: a project puts
`image-sources.json` at its root (overridable with `SPS_IMAGE_SOURCES`) naming
the providers it may use. Missing declaration means *unavailable*, not "probably
fine" — the contract is fail-closed so nothing downstream can promise an asset
nobody can fetch.

Both readers went to different conclusions about the same file before:
`check_claude_pptx_env.py` reported it as an environment status, and
`art_direction_check.py` (plan time) never asked at all — so an `asset_plan` could
declare `hero_visuals: 2` while no image was obtainable, and the resulting
`hero-visual-missing` blocker repeated every critique round with no way to fix it
inside the repair budget (2026-09-17 live: it survived from the first review to
the last). Same file, same question, one function.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

IMAGE_SOURCE_CONFIG_NAME = "image-sources.json"


def command_path(name: str, extra_paths: list[Path] | None = None) -> str | None:
    """PATH probe that tolerates Windows' extension-less command names."""
    if os.name == "nt" and not Path(name).suffix:
        for suffix in (".cmd", ".exe", ".bat"):
            found = shutil.which(name + suffix)
            if found:
                return found
    found = shutil.which(name)
    if found:
        return found
    for path in extra_paths or []:
        if path.is_file():
            return str(path)
    return None


def image_source_config_path(project: Path) -> Path | None:
    """Discovery order: `SPS_IMAGE_SOURCES` → `<project>/image-sources.json` → none."""
    override = os.environ.get("SPS_IMAGE_SOURCES", "").strip()
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    candidate = project / IMAGE_SOURCE_CONFIG_NAME
    return candidate if candidate.is_file() else None


def resolve_image_sources(project: Path) -> dict[str, Any]:
    """读项目里的 image-sources.json，报告 search/generation/user-assets 是否就绪。

    未配置时返回安全的"未声明"状态，不把缺失当成错误。
    """
    config_path = image_source_config_path(project)
    base = {
        "ok": False,
        "configured": False,
        "config_path": str(config_path) if config_path else None,
        "search_ready": False,
        "generation_ready": False,
        "user_assets_ready": False,
        "permission": {},
        "providers": [],
        "detail": "No image-sources.json declared; image search and generation are treated as unavailable.",
    }
    if config_path is None:
        return base

    try:
        from shared.pptx_runtime.fetch_images import load_image_sources_contract, resolve_assets_dir

        raw = load_image_sources_contract(config_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        base["configured"] = True
        base["detail"] = f"image-sources.json could not be read: {exc}"
        return base

    if not isinstance(raw, dict) or not isinstance(raw.get("providers"), list):
        base["configured"] = True
        base["detail"] = "image-sources.json must contain a providers array."
        return base

    permission = raw.get("permission") if isinstance(raw.get("permission"), dict) else {}
    # 缺省即拒绝（fail-closed），与执行侧 fetch_images.py 的真值判定保持一致。
    # 旧写法 `is not False` 会在字段缺失时放行，导致环境检查报 ready、实际却被跳过。
    allow_search = permission.get("allow_web_search") is True
    allow_generation = permission.get("allow_generation") is True

    providers: list[dict[str, Any]] = []
    search_ready = generation_ready = user_assets_ready = False
    for entry in raw["providers"]:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "")
        enabled = bool(entry.get("enabled"))
        record: dict[str, Any] = {
            "id": entry.get("id"),
            "kind": kind,
            "enabled": enabled,
            "capability": entry.get("capability"),
            "permission": entry.get("permission"),
        }
        missing_commands = [
            name
            for name in (entry.get("requires") or [])
            if command_path(str(name)) is None
        ]
        record["missing_commands"] = missing_commands

        if not enabled:
            record["available"] = False
            record["reason"] = "disabled"
        elif kind == "user-assets":
            assets_dir = entry.get("assets_dir") or "assets"
            resolved = resolve_assets_dir(str(assets_dir), project)
            available = bool(resolved and resolved.is_dir())
            record["available"] = available
            if resolved is None:
                record["reason"] = "assets_dir escapes project root"
            else:
                record["reason"] = None if available else "assets_dir missing"
            record["assets_dir"] = str(resolved) if resolved else None
            user_assets_ready = user_assets_ready or available
        elif kind == "web-search":
            available = allow_search and not missing_commands
            record["available"] = available
            record["reason"] = (
                None if available else ("permission denied" if not allow_search else "required command missing")
            )
            search_ready = search_ready or available
        elif kind == "image-generation":
            available = allow_generation and bool(entry.get("capability")) and not missing_commands
            record["available"] = available
            record["reason"] = (
                None
                if available
                else (
                    "permission denied"
                    if not allow_generation
                    else "missing capability declaration or required command"
                )
            )
            generation_ready = generation_ready or available
        else:
            record["available"] = False
            record["reason"] = "unknown provider kind"
        providers.append(record)

    declared = bool(providers)
    return {
        "ok": declared,
        "configured": True,
        "config_path": str(config_path),
        "search_ready": search_ready,
        "generation_ready": generation_ready,
        "user_assets_ready": user_assets_ready,
        "permission": permission,
        "providers": providers,
        "detail": (
            f"{len(providers)} provider(s) declared; "
            f"search_ready={search_ready}, generation_ready={generation_ready}, "
            f"user_assets_ready={user_assets_ready}."
        ),
    }


def imagery_available(sources: dict[str, Any] | None) -> bool:
    """任何一类外部图片能力就绪都算可用；未声明或全部不可用即 False。

    `None` 表示调用方没有解析过（而不是"不可用"），返回 False 会让 plan 把
    "未问过"当成"没有"，所以调用方必须先解析再判断。
    """
    if not isinstance(sources, dict):
        return False
    return any(
        bool(sources.get(key))
        for key in ("search_ready", "generation_ready", "user_assets_ready")
    )
