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
import re
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
# Batch 0 metrics (v0.15 pipeline-simplification baseline).
# A "deterministic round-trip" is a model turn whose every tool call merely drives a
# deterministic pipeline command — state polling, gates, build, render, preview. These
# are the rounds `ppt_pipeline.py advance` (Batch 3) is meant to absorb without the
# model seeing results and issuing the next command by hand.
DETERMINISTIC_COMMAND = re.compile(
    r"(ppt_pipeline\.py|run_gates\.(?:py|sh)|calibration_preview\.py)\b"
)
# Shared-context artifacts whose repeated reads measure duplication across builders
# and rounds (Batch 2's Builder Packet targets exactly this).
SHARED_ARTIFACT = re.compile(
    r"(slide-spec-compiled|art-direction|build-manifest|research-pack|pipeline-qa|gates-report)",
    re.I,
)
PAGE_BRIEF_WD = re.compile(r"--work-dir[ =]+[\"']?([^\"'\s]+)", re.I)
BYTES_PER_TOKEN_ESTIMATE = 4


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
    return "" if content is None else json.dumps(content, ensure_ascii=False                )


def collapse_duplicate_requests(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per API call: within a message id, keep the row reporting the FULL prompt.

    Claude Code writes one assistant message as several transcript rows (streaming
    partials, one per content block). The early rows report an intermediate context;
    only the completed row carries the real prompt — measured 2026-09-18:

        ctx=68,666  out=0     stop=None      [thinking]
        ctx=699,497 out=1,633 stop=end_turn  [text]      <- the same API call

    Grouping by message id and keeping the max-context row reproduces the real prompt
    (independently checked: that conversation's text sizes to ~718K by hand). The old
    rule — merge consecutive rows with *identical* usage inside 2s — left the differing
    partials in place, so a subagent read as 480 requests where 261 were sent, and every
    per-turn figure derived from it was wrong by ~1.8x.

    Rows without a message id keep the older identical-usage rule, so transcripts that
    carry no ids stay countable instead of being reported as one request per content block.
    """
    slots: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for item in requests:
        key = str(item.get("message_id") or "")
        if not key:
            slots.append(dict(item, copies=1))
            continue
        current = by_id.get(key)
        if current is None:
            merged = dict(item, copies=1)
            by_id[key] = merged
            slots.append(merged)
        elif item["context"] >= current["context"]:
            carried = list(current.get("tool_ids") or [])
            current.update(item)
            # Merge, never replace: the rows of one message carry DISJOINT content blocks, so
            # replacing here is what made a batching session look like one call per turn.
            current["tool_ids"] = list(dict.fromkeys([*carried, *(item.get("tool_ids") or [])]))
            current["copies"] = int(current.get("copies") or 1) + 1
        else:
            current["tool_ids"] = list(dict.fromkeys([*(current.get("tool_ids") or []), *(item.get("tool_ids") or [])]))
            current["copies"] = int(current.get("copies") or 1) + 1

    collapsed: list[dict[str, Any]] = []
    for item in slots:
        if collapsed and not item.get("message_id"):
            prev = collapsed[-1]
            gap = 999.0
            if item["ts"] and prev["ts"]:
                gap = (item["ts"] - prev["ts"]).total_seconds()
            same = (
                item["context"] == prev["context"]
                and item["fresh"] == prev["fresh"]
                and item["cache_read"] == prev["cache_read"]
                and item["cache_write"] == prev["cache_write"]
                and item["output"] == prev["output"]
            )
            if gap <= 2.0 and same:
                prev["copies"] = int(prev.get("copies") or 1) + 1
                prev["tool_ids"] = list(dict.fromkeys([*(prev.get("tool_ids") or []), *(item.get("tool_ids") or [])]))
                continue
        collapsed.append(item)
    return collapsed


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
                        "ts": stamp,
                        "message_id": message.get("id"),
                        "context": (usage.get("input_tokens") or 0)
                        + (usage.get("cache_creation_input_tokens") or 0)
                        + (usage.get("cache_read_input_tokens") or 0),
                        "fresh": usage.get("input_tokens") or 0,
                        "cache_write": usage.get("cache_creation_input_tokens") or 0,
                        "cache_read": usage.get("cache_read_input_tokens") or 0,
                        "output": usage.get("output_tokens") or 0,
                        # Tool calls are counted as the UNION per message id, not per row:
                        # Claude Code splits one message's content blocks across rows, so a
                        # per-row count caps at 1 and reports a batching-capable session as
                        # "one call per turn" (measured 2026-09-18: per-row said max 1, the
                        # union said max 8 with 19.8% of turns batched).
                        "tool_ids": [
                            str(block.get("id") or f"{block.get('name')}:{index}")
                            for index, block in enumerate(message.get("content") or [])
                            if isinstance(block, dict) and block.get("type") == "tool_use"
                        ],
                        "tool_calls": 0,
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
                    entry = {
                        "name": name,
                        "in_bytes": len(payload.encode("utf-8")),
                        "out_bytes": 0,
                        "sec": None,
                        "start": stamp,
                        "preview": payload[:120].replace("\n", " "),
                    }
                    # Batch 0 metrics need the raw invocation, not the truncated preview.
                    if name == "Bash":
                        entry["cmd"] = str((block.get("input") or {}).get("command") or "")
                    elif name == "Read":
                        entry["path"] = str((block.get("input") or {}).get("file_path") or "")
                    tools[str(block.get("id"))] = entry
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

    requests = collapse_duplicate_requests(requests)
    contexts = [item["context"] for item in requests]
    # One turn's tool calls = the union of every block row of that message id.
    for item in requests:
        item["tool_calls"] = len(set(item.get("tool_ids") or []))
    batch_sizes = [item["tool_calls"] for item in requests]
    batched_turns = sum(1 for value in batch_sizes if value >= 2)
    fresh = sum(item["fresh"] for item in requests)
    cache_write = sum(item["cache_write"] for item in requests)
    cache_read = sum(item["cache_read"] for item in requests)
    output = sum(item["output"] for item in requests)
    duration = (last_ts - first_ts).total_seconds() if (first_ts and last_ts) else None
    # Wall clock includes any idle before the first request and after the last
    # one (a stalled balance error, a long think, a tab left open). Per-request
    # cost has to be measured against the span the model was actually working,
    # otherwise a single stall inflates every request in the report.
    stamps = [item["ts"] for item in requests if item["ts"]]
    work_span = (stamps[-1] - stamps[0]).total_seconds() if len(stamps) >= 2 else None
    # Gap between consecutive turns, ignoring the long stalls: a turn ON the critical path
    # is what a time budget has to pay for, and a multi-hour wait for a user answer is not.
    gaps = []
    for index in range(1, len(stamps)):
        gap = (stamps[index] - stamps[index - 1]).total_seconds()
        if 0 < gap < 300:
            gaps.append(gap)

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

    # --- Batch 0 metrics -----------------------------------------------------
    # Turns spent purely driving deterministic pipeline commands: the exact
    # population `ppt_pipeline.py advance` (Batch 3) should absorb.
    deterministic_roundtrips = 0
    for item in requests:
        call_ids = set(item.get("tool_ids") or [])
        entries = [tools[tid] for tid in call_ids if tid in tools]
        if entries and all(
            entry["name"] == "Bash"
            and entry.get("cmd")
            and DETERMINISTIC_COMMAND.search(entry["cmd"])
            for entry in entries
        ):
            deterministic_roundtrips += 1
    # Repeated reads of shared context artifacts (spec / art direction / manifest /
    # QA / research pack / page_brief per work-dir). Duplication beyond the first
    # read is estimated from tool-result bytes; ~4 bytes per token.
    shared_reads: dict[str, dict[str, int]] = {}
    for entry in tools.values():
        key = None
        if entry["name"] == "Read":
            text = str(entry.get("path") or "").replace("\\", "/")
            if SHARED_ARTIFACT.search(text):
                key = "read:" + text.lower()
        elif entry["name"] == "Bash" and "page_brief.py" in str(entry.get("cmd") or ""):
            match = PAGE_BRIEF_WD.search(str(entry.get("cmd") or ""))
            if match:
                key = "page_brief:" + match.group(1).replace("\\", "/").lower()
        if key:
            slot = shared_reads.setdefault(key, {"bytes": 0, "reads": 0})
            slot["bytes"] += entry["out_bytes"]
            slot["reads"] += 1
    duplicated_reads = {key: slot for key, slot in shared_reads.items() if slot["reads"] > 1}
    duplication_bytes = sum(
        slot["bytes"] * (slot["reads"] - 1) / slot["reads"]
        for slot in duplicated_reads.values()
    )

    return {
        "started_at": first_ts.isoformat() if first_ts else None,
        "ended_at": last_ts.isoformat() if last_ts else None,
        "duration_sec": round(duration, 1) if duration else None,
        "work_span_sec": round(work_span, 1) if work_span else None,
        "idle_sec": round(duration - work_span, 1) if (duration and work_span) else None,
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
        "per_request_sec": round(work_span / len(requests), 2) if (work_span and requests) else None,
        # Turn economy: wall clock is turns x round-trip latency, and the gates themselves
        # cost seconds (2026-09-18: 150s across the whole suite = 1.7% of a 147-min run).
        # So the number that predicts whether a deck fits a time budget is turns and how
        # many tool calls each turn carries — 1.0/turn means the model waits for every call.
        "turns": len(requests),
        "tool_calls_per_turn": (
            round(sum(batch_sizes) / len(batch_sizes), 2) if batch_sizes else None
        ),
        "batched_turns": batched_turns,
        "batched_turn_share": (
            round(batched_turns / len(batch_sizes), 3) if batch_sizes else None
        ),
        "largest_batch": max(batch_sizes, default=0),
        "turn_seconds": {
            "median": (
                sorted(gaps)[len(gaps) // 2] if gaps else None
            ),
            "p90": (sorted(gaps)[min(len(gaps) - 1, int(len(gaps) * 0.9))] if gaps else None),
            "mean": (round(sum(gaps) / len(gaps), 1) if gaps else None),
        },
        "turns_under_20min": {
            "at_median": (round(1200 / sorted(gaps)[len(gaps) // 2]) if gaps else None),
            "at_mean": (round(1200 / (sum(gaps) / len(gaps))) if gaps else None),
        },
        # Batch 0 baseline metrics (v0.15 targets: deterministic round-trips ↓70%,
        # shared-context duplication ↓ via Builder Packet). Duplication token count is
        # an ESTIMATE from tool-result bytes at ~4 bytes/token, not a transcript token count.
        "deterministic_agent_roundtrips": deterministic_roundtrips,
        "deterministic_roundtrip_share": (
            round(deterministic_roundtrips / len(requests), 3) if requests else None
        ),
        "shared_context_duplication_tokens": round(duplication_bytes / BYTES_PER_TOKEN_ESTIMATE),
        "shared_context_duplication_reads": {
            key: slot["reads"]
            for key, slot in sorted(duplicated_reads.items(), key=lambda item: -item[1]["reads"])
        },
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
    work = summary.get("work_span_sec")
    span = summary.get("duration_sec")
    idle = summary.get("idle_sec")
    if work and span and idle is not None and idle > work * 0.5:
        notes.append(
            f"空转 {idle / 60:.1f} 分钟，占墙钟 {idle / span * 100:.0f}%（长于工作时长的一半）；"
            "排查中断点：余额/限流报错、等待用户确认、子代理未回收"
        )
    per_turn = summary.get("tool_calls_per_turn")
    largest = summary.get("largest_batch") or 0
    if per_turn is not None and per_turn < 1.6 and (summary.get("turns") or 0) >= 40:
        if largest >= 2:
            notes.append(
                f"回合经济：平均 {per_turn} 个调用/回合，但单回合出现过 {largest} 个——"
                "说明批处理可用，只是任务形态把调用串成了依赖链（改一次→验一次）。"
                "把互相独立的动作（多页写入、多张图读取）放进同一回合，或把页面拆给并行 builder"
            )
        else:
            notes.append(
                f"回合经济：每回合只有 {per_turn} 个调用且从未出现过并行调用。逐回合等一个往返"
                "是墙钟的全部来源——先确认并行调用这条路是否被 prompt 关掉了（本仓库 2026-09-18 "
                "实测：精简体 system prompt 不含并行指令），再考虑把工作拆给并行 builder"
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
        + (f"\n- time: work span {summary['work_span_sec'] / 60:.1f} min"
           f" | idle {summary['idle_sec'] / 60:.1f} min"
           f" | wall clock {duration / 60:.1f} min"
           if (duration and summary["work_span_sec"] and summary["idle_sec"] is not None)
           else f" ({duration / 60:.1f} min)" if duration else ""),
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
        "## Turn economy (墙钟 = 回合数 × 往返延迟；门本身只花秒级)",
        f"- turns: **{summary.get('turns')}** | tool calls per turn: "
        f"**{summary.get('tool_calls_per_turn')}** | batched turns: "
        f"{summary.get('batched_turns')} ({float(summary.get('batched_turn_share') or 0) * 100:.1f}%)"
        f" | largest batch: {summary.get('largest_batch')}",
        f"- 批处理可用性：单回合曾出现 {summary.get('largest_batch')} 个调用，"
        "所以「一个调用一个回合」是任务形态（串行依赖）造成的，不是能力上限；"
        "把独立工作（多页写入、多张图读取）放在同一回合即可减少回合数",
        f"- per-turn seconds: median {summary['turn_seconds']['median']} / "
        f"p90 {summary['turn_seconds']['p90']} / mean {summary['turn_seconds']['mean']}",
        f"- 20 分钟预算可容纳的回合数：中位延迟下 **{summary['turns_under_20min']['at_median']}** 回合、"
        f"均值延迟下 {summary['turns_under_20min']['at_mean']} 回合",
        "",
        "## Batch 0 baseline metrics (v0.15 简化系列)",
        f"- deterministic agent round-trips: **{summary.get('deterministic_agent_roundtrips')}** / "
        f"{summary.get('turns')} turns"
        "（全部工具调用都只是驱动 ppt_pipeline / run_gates / calibration_preview 的回合，"
        "Batch 3 `advance` 的吸收目标）",
        f"- shared-context duplication: ~**{summary.get('shared_context_duplication_tokens'):,}** tokens"
        "（估算值，按 4 bytes/token；同一份 spec / art-direction / manifest / QA / research-pack "
        "或同一 work-dir 的 page_brief 被重复读取的部分，Batch 2 Builder Packet 的压缩目标）",
    ]
    duplicated_reads = summary.get("shared_context_duplication_reads") or {}
    for key, reads in list(duplicated_reads.items())[:5]:
        lines.append(f"  - {key} ×{reads}")
    lines.append("")
    lines.append("## Context buckets")
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
