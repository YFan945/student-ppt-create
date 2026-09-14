#!/usr/bin/env python3
"""Report the context/token cost profile of a Claude Code session.

A session's token bill is dominated by session *structure*, not task difficulty:

    total tokens ~= requests x average resident context
    wall clock   ~= requests x per-request prefill time

Both multipliers are invisible while you work. This script reads a session
transcript and prints what actually happened: the token ledger, the context
growth curve, per-tool cost, and the specific habits that inflated them (whole
product of `references/cost-discipline.md`).

Transcripts live in ``<CLAUDE_CONFIG_DIR or ~/.claude>/projects/<project>/<session>.jsonl``.

Usage:
    python scripts/session_cost.py                    # newest session, markdown
    python scripts/session_cost.py --list             # show candidates
    python scripts/session_cost.py --last 3
    python scripts/session_cost.py --session <path> --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
DEFAULT_ROOT = CONFIG_DIR / "projects"
CONTEXT_BUCKETS = ((40_000, "<40K"), (80_000, "40-80K"), (120_000, "80-120K"), (160_000, "120-160K"), (200_000, "160-200K"))
HEAVY_CONTEXT = 200_000
DEFAULT_CURVE_POINTS = 12


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def discover(root: Path, *, include_subagents: bool = False) -> list[Path]:
    if not root.is_dir():
        return []
    found: list[Path] = []
    for path in root.rglob("*.jsonl"):
        if not include_subagents and "subagents" in path.parts:
            continue
        found.append(path)
    found.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return found


def read_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(value)
    return records


def block_text(block: Any) -> str:
    content = block.get("content") if isinstance(block, dict) else None
    if isinstance(content, list):
        return "".join(
            (item.get("text") or "") if isinstance(item, dict) else str(item) for item in content
        )
    if isinstance(content, str):
        return content
    return "" if content is None else json.dumps(content, ensure_ascii=False)


def profile(records: list[dict[str, Any]]) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    tools: dict[str, dict[str, Any]] = {}
    writes_by_path: Counter[str] = Counter()
    edits_by_path: Counter[str] = Counter()
    tool_calls: Counter[str] = Counter()
    thinking_chars = 0
    text_chars = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None

    for record in records:
        stamp = parse_timestamp(record.get("timestamp"))
        if stamp:
            first_ts = first_ts or stamp
            last_ts = stamp
        message = record.get("message") or {}
        kind = record.get("type")

        if kind == "assistant":
            usage = message.get("usage")
            if isinstance(usage, dict):
                requests.append(
                    {
                        "context": (usage.get("input_tokens") or 0)
                        + (usage.get("cache_creation_input_tokens") or 0)
                        + (usage.get("cache_read_input_tokens") or 0),
                        "fresh": usage.get("input_tokens") or 0,
                        "cache_write": usage.get("cache_creation_input_tokens") or 0,
                        "cache_read": usage.get("cache_read_input_tokens") or 0,
                        "output": usage.get("output_tokens") or 0,
                    }
                )
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text_chars += len(block.get("text") or "")
                elif block.get("type") == "thinking":
                    thinking_chars += len(block.get("thinking") or "")
                elif block.get("type") == "tool_use":
                    name = str(block.get("name") or "?")
                    payload = json.dumps(block.get("input") or {}, ensure_ascii=False)
                    tool_calls[name] += 1
                    tools[str(block.get("id"))] = {
                        "name": name,
                        "in_bytes": len(payload.encode("utf-8")),
                        "out_bytes": 0,
                        "sec": None,
                        "start": stamp,
                        "preview": payload[:120].replace("\n", " "),
                    }
                    # Only whole-file Writes count against CD-2; precise Edits are
                    # the behaviour CD-2 asks for, so they are reported separately.
                    if name in {"Write", "Edit"}:
                        target = (block.get("input") or {}).get("file_path")
                        if target:
                            counter = writes_by_path if name == "Write" else edits_by_path
                            counter[str(target)] += 1

        elif kind == "user":
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                entry = tools.get(str(block.get("tool_use_id")))
                if entry is None:
                    continue
                entry["out_bytes"] = len(block_text(block).encode("utf-8"))
                finish = parse_timestamp(record.get("timestamp"))
                if finish and entry["start"]:
                    entry["sec"] = (finish - entry["start"]).total_seconds()

    contexts = [item["context"] for item in requests]
    fresh = sum(item["fresh"] for item in requests)
    cache_write = sum(item["cache_write"] for item in requests)
    cache_read = sum(item["cache_read"] for item in requests)
    output = sum(item["output"] for item in requests)
    duration = (last_ts - first_ts).total_seconds() if (first_ts and last_ts) else None

    buckets: Counter[str] = Counter()
    for value in contexts:
        for ceiling, label in CONTEXT_BUCKETS:
            if value < ceiling:
                buckets[label] += 1
                break
        else:
            buckets["200K+"] += 1

    growth: list[dict[str, Any]] = []
    for index in range(1, len(contexts)):
        delta = contexts[index] - contexts[index - 1]
        if delta > 0:
            growth.append({"request": index + 1, "delta": delta, "context": contexts[index]})
    growth.sort(key=lambda item: -item["delta"])

    by_tool: dict[str, dict[str, Any]] = {}
    for entry in tools.values():
        slot = by_tool.setdefault(
            entry["name"], {"calls": 0, "in_bytes": 0, "out_bytes": 0, "sec": 0.0}
        )
        slot["calls"] += 1
        slot["in_bytes"] += entry["in_bytes"]
        slot["out_bytes"] += entry["out_bytes"]
        slot["sec"] += entry["sec"] or 0.0

    return {
        "started_at": first_ts.isoformat() if first_ts else None,
        "ended_at": last_ts.isoformat() if last_ts else None,
        "duration_sec": round(duration, 1) if duration else None,
        "requests": len(requests),
        "tool_calls": sum(tool_calls.values()),
        "tool_calls_by_name": dict(tool_calls.most_common()),
        "tokens": {
            "fresh_input": fresh,
            "cache_write": cache_write,
            "cache_read": cache_read,
            "output": output,
            "total": fresh + cache_write + cache_read + output,
        },
        "context": {
            "average": round(sum(contexts) / len(contexts)) if contexts else 0,
            "median": sorted(contexts)[len(contexts) // 2] if contexts else 0,
            "peak": max(contexts, default=0),
            "buckets": dict(buckets),
            "heavy_requests": sum(1 for value in contexts if value >= HEAVY_CONTEXT),
        },
        "per_request_sec": round(duration / len(requests), 2) if (duration and requests) else None,
        "assistant_text_chars": text_chars,
        "assistant_thinking_chars": thinking_chars,
        "context_curve": [
            {"request": index + 1, "context": value}
            for index, value in enumerate(contexts)
            if index % max(1, len(contexts) // DEFAULT_CURVE_POINTS) == 0
        ],
        "top_growth": growth[:10],
        "by_tool": dict(sorted(by_tool.items(), key=lambda item: -(item[1]["in_bytes"] + item[1]["out_bytes"]))),
        "rewritten_files": [{"file": key, "writes": count} for key, count in writes_by_path.items() if count > 1],
        "written_files": len(writes_by_path),
        "in_place_edits": dict(edits_by_path.most_common()),
    }


def warnings(summary: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    context = summary["context"]
    tokens = summary["tokens"]
    if context["heavy_requests"] and summary["requests"]:
        share = context["heavy_requests"] / summary["requests"] * 100
        notes.append(
            f"上下文 ≥20 万 token 的请求 {context['heavy_requests']}/{summary['requests']} 次（{share:.1f}%）；"
            "阶段小结落盘可压低常驻基线（CD-4）"
        )
    if summary["tool_calls"] and summary["requests"]:
        ratio = summary["requests"] / summary["tool_calls"]
        if ratio >= 1.8:
            notes.append(
                f"每次工具调用消耗 {ratio:.2f} 个请求往返；把可并行的调用合并到同一轮可显著降低往返（CD-1）"
            )
    for item in summary["rewritten_files"]:
        notes.append(f"整文件重写：{Path(item['file']).name} 被写入 {item['writes']} 次（CD-2 禁止）")
    if tokens["cache_read"] and tokens["total"]:
        notes.append(
            f"cache-read 占总量 {tokens['cache_read'] / tokens['total'] * 100:.1f}%；"
            "这部分是同一份上下文的重复计费，不是新增工作"
        )
    return notes


def render_markdown(summary: dict[str, Any], source: Path) -> str:
    tokens = summary["tokens"]
    context = summary["context"]
    duration = summary["duration_sec"]
    lines = [
        "# Session cost report",
        "",
        f"- file: `{source}`",
        f"- window: {summary['started_at']} → {summary['ended_at']}"
        + (f" ({duration / 60:.1f} min)" if duration else ""),
        "",
        "## Headline",
        f"- requests: **{summary['requests']}** | tool calls: {summary['tool_calls']}"
        + (f" | {summary['per_request_sec']} s/request" if summary["per_request_sec"] else ""),
        f"- context: avg **{context['average']:,}** | median {context['median']:,} | peak {context['peak']:,}",
        f"- tokens: total **{tokens['total']:,}** (fresh {tokens['fresh_input']:,} / "
        f"cache-write {tokens['cache_write']:,} / cache-read {tokens['cache_read']:,} / "
        f"output {tokens['output']:,})",
        f"- 乘法模型：{summary['requests']} 请求 × {context['average']:,} ≈ "
        f"{summary['requests'] * context['average']:,} token",
        "",
        "## Context buckets",
    ]
    for label in [item[1] for item in CONTEXT_BUCKETS] + ["200K+"]:
        count = context["buckets"].get(label, 0)
        if count:
            lines.append(f"- {label}: {count}")
    lines.append("")
    lines.append("## Context growth (sampled)")
    lines.append("")
    lines.append("| request | context |")
    lines.append("| ---: | ---: |")
    for point in summary["context_curve"]:
        lines.append(f"| {point['request']} | {point['context']:,} |")
    lines.append("")
    lines.append("## Tools")
    lines.append("")
    lines.append("| tool | calls | in | out | sec |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for name, slot in summary["by_tool"].items():
        lines.append(
            f"| {name} | {slot['calls']} | {slot['in_bytes'] / 1024:.0f}K | "
            f"{slot['out_bytes'] / 1024:.0f}K | {slot['sec']:.0f} |"
        )
    edits = sum(summary["in_place_edits"].values())
    lines.append("")
    lines.append(
        f"- whole-file writes: {summary['written_files']} file(s) | "
        f"in-place edits: {edits} （CD-2 期望做法）"
    )
    lines.append("")
    lines.append("## Biggest single-step context jumps")
    lines.append("")
    for item in summary["top_growth"][:5]:
        lines.append(f"- request #{item['request']}: +{item['delta']:,} → {item['context']:,}")
    notes = warnings(summary)
    if notes:
        lines.append("")
        lines.append("## Warnings")
        for note in notes:
            lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def resolve_sessions(args: argparse.Namespace) -> list[Path]:
    if args.session:
        return [Path(args.session)]
    candidates = discover(Path(args.sessions_root), include_subagents=args.include_subagents)
    if args.project:
        needle = args.project.replace("\\", "-").replace("/", "-").lower()
        candidates = [item for item in candidates if needle in str(item.parent).lower()]
    return candidates[: max(1, args.last)]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", type=Path, help="explicit transcript path")
    parser.add_argument("--project", help="filter by project directory name (e.g. E--test-ppt)")
    parser.add_argument("--last", type=int, default=1, help="how many recent sessions to report (default 1)")
    parser.add_argument("--list", action="store_true", help="list candidate transcripts and exit")
    parser.add_argument("--sessions-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--include-subagents", action="store_true", help="also include subagent transcripts")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sessions = resolve_sessions(args)
    if args.list or not sessions:
        if not sessions:
            print(f"no transcripts under {args.sessions_root}", file=sys.stderr)
        for path in discover(Path(args.sessions_root), include_subagents=args.include_subagents)[:20]:
            stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"{stamp}  {path.stat().st_size / 1048576:7.2f} MB  {path}")
        return 0 if sessions or args.list else 2

    payload = []
    for path in sessions:
        summary = profile(read_records(path))
        summary["file"] = str(path)
        summary["warnings"] = warnings(summary)
        payload.append(summary)

    if args.json:
        print(json.dumps(payload if len(payload) > 1 else payload[0], ensure_ascii=False, indent=2))
    else:
        for summary, path in zip(payload, sessions, strict=True):
            print(render_markdown(summary, path), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
