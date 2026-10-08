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
- ``{query}``, ``{url}`` and ``{output}`` are substituted only when the
  placeholder is an entire argv entry;
- shell wrappers (sh, bash, dash, zsh, cmd, powershell, pwsh) are rejected;
- every command runs with a timeout and a result file is accepted only when
  its resolved path stays inside the requested output directory.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# 跨 query 并行抓取的线程上限。provider 命令大多是网络等待，4 个并发足以把
# 串行逐条等待压成 ~1/4 墙钟，又不至于触发图库/provider 的速率限制。
MAX_PARALLEL_QUERIES = 4

_PLACEHOLDER = re.compile(r"\{(query|url|output)\}")
_SHELLS = frozenset({"sh", "bash", "dash", "zsh", "cmd", "powershell", "pwsh"})
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "references" / "image-sources.schema.json"


def _slug(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "-", text.strip()).strip("-").lower()
    return slug[:60] or "query"


def resolve_assets_dir(raw: str, project_root: Path) -> Path | None:
    """Return ``raw`` resolved under ``project_root``, or None if it escapes."""
    root = Path(project_root).resolve()
    path = Path(raw)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def load_image_sources_contract(path: Path) -> dict[str, Any]:
    """Load and schema-validate an image-sources.json contract."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    import jsonschema

    jsonschema.Draft202012Validator.check_schema(schema)
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(data),
        key=lambda err: list(err.path),
    )
    if errors:
        details = "; ".join(
            f"{'/'.join(str(part) for part in err.path) or '<root>'}: {err.message}"
            for err in errors
        )
        raise ValueError(f"image-sources.json failed schema validation: {details}")
    return data


def _check_gates(
    sources: dict[str, Any],
    approved_commands: set[str] | None = None,
    project_root: Path | None = None,
) -> tuple[list[dict], list[str]]:
    """Return (runnable providers, skip reasons) after permission + env gates."""
    permission = sources.get("permission") or {}
    runnable: list[dict[str, Any]] = []
    reasons: list[str] = []
    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
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
        if kind in {"web-search", "image-generation"}:
            command_hash = hashlib.sha256(str(provider.get("command") or "").encode("utf-8")).hexdigest()
            if command_hash not in (approved_commands or set()):
                reasons.append(f"{pid}: command requires independent user approval: {command_hash}")
                continue
        missing = [cmd for cmd in provider.get("requires", []) if not shutil.which(cmd)]
        if missing:
            reasons.append(f"{pid}: required commands missing: {', '.join(missing)}")
            continue
        entry = dict(provider)
        if kind == "user-assets":
            resolved = resolve_assets_dir(str(provider.get("assets_dir") or "assets"), root)
            if resolved is None:
                reasons.append(f"{pid}: assets_dir escapes project root")
                continue
            if not resolved.is_dir():
                reasons.append(f"{pid}: assets_dir missing")
                continue
            entry["_resolved_assets_dir"] = str(resolved)
        runnable.append(entry)
    return runnable, reasons


def _collect_user_assets(provider: dict[str, Any], query: str, out_dir: Path) -> dict[str, Any] | None:
    assets_dir = Path(provider.get("_resolved_assets_dir") or provider.get("assets_dir", "assets"))
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
    rendered = _render_command(str(command_template), placeholders)
    if isinstance(rendered, str):
        notes.append(f"{provider.get('id')}: {rendered}")
        return None
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
    if not output.exists() or output.is_dir() or output.stat().st_size == 0:
        notes.append(f"{provider.get('id')}: command produced no output file")
        return None
    resolved = output.resolve()
    root = out_dir.resolve()
    if resolved != root and root not in resolved.parents:
        notes.append(f"{provider.get('id')}: output escapes the output directory")
        return None
    return {"path": output, "source_url": placeholders["url"] or None}


def _argv0_name(token: str) -> str:
    name = Path(token).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def _render_command(command_template: str, placeholders: dict[str, str]) -> list[str] | str:
    """Placeholders stay whole argv entries. Shell wrappers are not a template."""
    try:
        parts = shlex.split(command_template)
    except ValueError as exc:
        return f"command template could not be parsed: {exc}"
    if not parts:
        return "command template is empty"
    if _argv0_name(parts[0]) in _SHELLS:
        return "shell wrappers are not accepted; placeholders must be separate argv entries"
    rendered: list[str] = []
    for part in parts:
        if _PLACEHOLDER.fullmatch(part):
            rendered.append(placeholders[part[1:-1]])
            continue
        if _PLACEHOLDER.search(part):
            return "placeholders must be entire argv entries, not embedded in a script or flag"
        rendered.append(part)
    return rendered


def fetch_images(
    sources_path: Path,
    queries: list[str],
    out_dir: Path,
    timeout_sec: int = 120,
    approved_commands: set[str] | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Run the contract for every query. Returns a report dict.

    Queries run in parallel across a small thread pool; within one query the
    provider chain stays serial and priority-ordered so "first provider that
    returns an asset wins" keeps its meaning. Duplicate queries execute once
    and their records are repeated — two concurrent runs of the same provider
    command would otherwise race on the same output file.
    """
    sources = load_image_sources_contract(Path(sources_path))
    out_dir.mkdir(parents=True, exist_ok=True)
    root = Path(project_root).resolve() if project_root is not None else Path.cwd().resolve()
    runnable, gate_reasons = _check_gates(sources, approved_commands, project_root=root)
    now = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")

    def run_query(query: str, notes: list[str]) -> list[dict[str, Any]]:
        fetched: list[dict[str, Any]] = []
        for provider in runnable:
            kind = provider.get("kind")
            result = None
            if kind == "user-assets":
                result = _collect_user_assets(provider, query, out_dir)
            elif kind in ("web-search", "image-generation"):
                result = _run_command(provider, query, out_dir, timeout_sec, notes)
            if result is None:
                continue
            fetched.append(
                {
                    "query": query,
                    "provider_id": provider["id"],
                    "permission": provider.get("permission", "unknown"),
                    "path": str(result["path"]),
                    "source_url": result.get("source_url"),
                    "license": provider.get("permission", "unknown"),
                    "retrieved_at": now,
                    "status": "fetched",
                }
            )
            break
        if not fetched:
            fetched.append(
                {
                    "query": query,
                    "provider_id": None,
                    "status": "unfulfilled",
                    # 带上 provider 的失败细节，否则排查只能看到"无结果"。
                    "reason": "; ".join([*gate_reasons, *notes]) or "no provider returned an asset",
                }
            )
        return fetched

    unique: list[str] = []
    for query in queries:
        if query.strip() and query not in unique:
            unique.append(query)
    grouped: dict[str, list[dict[str, Any]]] = {}
    if len(unique) > 1:
        notes_by_query = {query: [] for query in unique}
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_QUERIES, len(unique))) as pool:
            fetched = pool.map(lambda item: run_query(item, notes_by_query[item]), unique)
            for query, records in zip(unique, fetched, strict=True):
                grouped[query] = records
    else:
        for query in unique:
            grouped[query] = run_query(query, [])

    records: list[dict[str, Any]] = []
    for query in queries:
        if not query.strip():
            continue
        records.extend(grouped.get(query) or [])

    return {
        "ok": all(r.get("status") == "fetched" for r in records) if records else True,
        "queries": queries,
        "gate_reasons": gate_reasons,
        "records": records,
        "retrieved_at": now,
    }
