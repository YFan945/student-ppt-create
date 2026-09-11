"""Execute image providers declared in an ``image-sources.json`` contract.

The contract declares permission gates and providers (user-assets copy,
web-search, image-generation). This module turns declarations into real
files: it copies user assets or runs each provider's ``command`` template
with ``{query}``, ``{url}`` and ``{output}`` placeholders, then records
provenance entries shaped like ``asset-manifest`` fields (without a slide
number, which only the authoring step knows).

Safety model:
- ``web-search`` providers require ``permission.allow_web_search: true``;
- ``image-generation`` providers require ``permission.allow_generation: true``;
- commands declared in ``requires`` must resolve on PATH or the provider is
  skipped with a recorded reason;
- every command runs with a timeout and its output must land inside the
  requested output directory.
"""

from __future__ import annotations

import datetime
import json
import re
import shlex
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any

_PLACEHOLDER = re.compile(r"\{(query|url|output)\}")


def _slug(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "-", text.strip()).strip("-").lower()
    return slug[:60] or "query"


def _check_gates(sources: dict[str, Any]) -> tuple[list[dict], list[str]]:
    """Return (runnable providers, skip reasons) after permission + env gates."""
    permission = sources.get("permission") or {}
    runnable: list[dict[str, Any]] = []
    reasons: list[str] = []
    for provider in sources.get("providers", []):
        pid = provider.get("id", "?")
        if not provider.get("enabled"):
            reasons.append(f"{pid}: disabled in contract")
            continue
        kind = provider.get("kind")
        if kind == "web-search" and not permission.get("allow_web_search"):
            reasons.append(f"{pid}: web search not permitted (allow_web_search=false)")
            continue
        if kind == "image-generation" and not permission.get("allow_generation"):
            reasons.append(f"{pid}: generation not permitted (allow_generation=false)")
            continue
        missing = [cmd for cmd in provider.get("requires", []) if not shutil.which(cmd)]
        if missing:
            reasons.append(f"{pid}: required commands missing: {', '.join(missing)}")
            continue
        runnable.append(provider)
    return runnable, reasons


def _collect_user_assets(provider: dict[str, Any], query: str, out_dir: Path) -> dict[str, Any] | None:
    assets_dir = Path(provider.get("assets_dir", "assets"))
    if not assets_dir.is_dir():
        return None
    tokens = [t for t in re.split(r"[\s,，、]+", query) if t]
    best: tuple[int, Path] | None = None
    for candidate in sorted(assets_dir.rglob("*")):
        if not candidate.is_file():
            continue
        stem = candidate.stem.lower()
        hits = sum(1 for token in tokens if token.lower() in stem)
        if hits == 0:
            continue
        if best is None or hits > best[0]:
            best = (hits, candidate)
    if best is None:
        return None
    dest = out_dir / f"{_slug(query)}-{_slug(str(provider.get('id') or 'provider'))}{best[1].suffix or '.bin'}"
    shutil.copyfile(best[1], dest)
    return {"path": dest, "source_url": None}


def _run_command(
    provider: dict[str, Any],
    query: str,
    out_dir: Path,
    timeout_sec: int,
    notes: list[str],
) -> dict[str, Any] | None:
    command_template = provider.get("command")
    if not command_template:
        return None
    slug = _slug(query)
    # provider id 来自 JSON 契约，必须与 query 一样净化：
    # 未净化的 id 可含 `../` 或分隔符，把文件写到 out_dir 之外。
    output = out_dir / f"{slug}-{_slug(str(provider.get('id') or 'provider'))}.img"
    placeholders = {
        "query": query,
        "url": provider.get("url_template", "").replace("{query}", urllib.parse.quote_plus(query)),
        "output": str(output),
    }
    # shlex 的 posix 模式默认会保留反斜杠（只在引号内转义），Windows 路径不会被吞；
    # 且只有 posix 模式才会剥离参数引号，非 posix 模式会让 `python -c "..."` 的实参
    # 带上字面引号而失效。因此始终用默认 posix 解析。
    parts = shlex.split(str(command_template))
    rendered = []
    for part in parts:
        rendered.append(_PLACEHOLDER.sub(lambda m: placeholders[m.group(1)], part))
    try:
        subprocess.run(
            rendered,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        notes.append(f"{provider.get('id')}: command timed out after {timeout_sec}s")
        return None
    except (subprocess.SubprocessError, OSError) as exc:
        # 旧实现静默丢弃 stdout/stderr，provider 失败原因完全不可诊断。
        detail = str(getattr(exc, "stderr", "") or "").strip()
        notes.append(f"{provider.get('id')}: {type(exc).__name__}: {exc} {detail}".rstrip())
        return None
    if not output.exists() or output.stat().st_size == 0:
        notes.append(f"{provider.get('id')}: command produced no output file")
        return None
    return {"path": output, "source_url": placeholders["url"] or None}


def fetch_images(
    sources_path: Path,
    queries: list[str],
    out_dir: Path,
    timeout_sec: int = 120,
) -> dict[str, Any]:
    """Run the contract for every query. Returns a report dict."""
    sources = json.loads(Path(sources_path).read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    runnable, gate_reasons = _check_gates(sources)
    now = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    records: list[dict[str, Any]] = []

    for query in queries:
        if not query.strip():
            continue
        fulfilled = False
        notes: list[str] = []
        for provider in runnable:
            kind = provider.get("kind")
            result = None
            if kind == "user-assets":
                result = _collect_user_assets(provider, query, out_dir)
            elif kind in ("web-search", "image-generation"):
                result = _run_command(provider, query, out_dir, timeout_sec, notes)
            if result is None:
                continue
            fulfilled = True
            record = {
                "query": query,
                "provider_id": provider["id"],
                "permission": provider.get("permission", "unknown"),
                "path": str(result["path"]),
                "source_url": result.get("source_url"),
                "license": provider.get("permission", "unknown"),
                "retrieved_at": now,
                "status": "fetched",
            }
            records.append(record)
            break
        if not fulfilled:
            records.append(
                {
                    "query": query,
                    "provider_id": None,
                    "status": "unfulfilled",
                    # 带上 provider 的失败细节，否则排查只能看到"无结果"。
                    "reason": "; ".join([*gate_reasons, *notes]) or "no provider returned an asset",
                }
            )

    return {
        "ok": all(r.get("status") == "fetched" for r in records) if records else True,
        "queries": queries,
        "gate_reasons": gate_reasons,
        "records": records,
        "retrieved_at": now,
    }
