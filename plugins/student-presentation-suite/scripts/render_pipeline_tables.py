#!/usr/bin/env python3
"""Render the README pipeline flow tables from the machine contract.

The READMEs used to hand-copy flow facts ("three gates", "at most one repair
loop") and drifted from `references/pipeline-contract.json` — five QA stages and
3+2 rounds — the moment the pipeline grew. This generator owns the table between
`<!-- pipeline-table:start -->` / `<!-- pipeline-table:end -->` markers; the
README prose only states user-facing modes and delivery guarantees. Numbers come
from the contract and the tier decision table (shared/quality_tiers.py), never
from this file.

Usage:
    python scripts/render_pipeline_tables.py            # rewrite both READMEs
    python scripts/render_pipeline_tables.py --check    # drift check (exit 2)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.quality_tiers import TIERS, tier_policy  # noqa: E402

CONTRACT_PATH = ROOT / "references" / "pipeline-contract.json"
READMES = {
    "en": ROOT / "README.md",
    "zh": ROOT / "README-zh.md",
}
MARKER_START = "<!-- pipeline-table:start -->"
MARKER_END = "<!-- pipeline-table:end -->"


def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def render_block(contract: dict, lang: str) -> str:
    """One generated block (markers included). Keep it short and flag-free."""
    states = " → ".join(f"`{name}`" for name in contract.get("workflow_states") or [])
    qa_order = " → ".join(f"`{name}`" for name in contract.get("qa_order") or [])
    max_repairs = contract.get("max_repairs")
    hard_cap = contract.get("max_repairs_hard_cap")
    pre_qa = contract.get("max_pre_qa_rebuilds")
    max_builders = contract.get("max_parallel_builders")

    rows = []
    for tier in TIERS:
        policy = tier_policy(tier)
        if lang == "zh":
            blocks = (
                "critical + 确定性失败"
                if tier == "fast"
                else "+ 结构性低分（hierarchy/focal_point）"
                if tier == "standard"
                else "+ 风格 Major + 视觉回归，单页底线 6.0"
            )
        else:
            blocks = (
                "critical + deterministic failures"
                if tier == "fast"
                else "+ structural lows (hierarchy/focal_point)"
                if tier == "standard"
                else "+ style majors + visual regression, per-slide floor 6.0"
            )
        rows.append(
            f"| `{tier}` | {policy['calibration_max_rounds']} | {policy['shard_cap']} | {blocks} |"
        )
    tier_rows = "\n".join(rows)

    if lang == "zh":
        return f"""{MARKER_START}
### 管线流程（由 references/pipeline-contract.json 生成，勿手改）

状态机：{states}（终止态 `incomplete` / `blocked`）。

QA 门按契约顺序执行：{qa_order}。`build` 打包后立即跑确定性 pre-QA（`rendered` +
`actual_content` + `quality` 门的确定性半部）；非确定性绿的 deck 不会进入 render 与 critic。

| 轮次预算 | 数值 |
| --- | --- |
| QA 返工轮（基数） | {max_repairs} |
| QA 返工轮（`repair --extend` 申报后硬上限） | {hard_cap} |
| pre-QA 免返工重建（不消耗返工预算） | {pre_qa} |
| 并行 Builder 分片上限（按档位收紧） | {max_builders} |

交付档位（`quality_level`，旧值 `basic` / `high-score` 作为别名兼容）：

| 档位 | 校准轮 | 分片上限 | 阻断项 |
| --- | --- | --- | --- |
{tier_rows}

交付保证：每个已确认产物在 `complete` 前按冻结 Slide Spec 核对内容与页数（PPTX/PDF 页数、
逐页讲稿段数），并绑定最终路径与哈希到 `outputs/` 目录。
{MARKER_END}"""
    return f"""{MARKER_START}
### Pipeline flow (generated from references/pipeline-contract.json — do not edit)

Workflow states: {states} (terminal: `incomplete` / `blocked`).

QA gates run in contract order: {qa_order}. Deterministic pre-QA (`rendered` +
`actual_content` + the quality gate's deterministic half) runs right after build; a
deck that is not deterministically green never reaches render or the critic.

| Round budget | Value |
| --- | --- |
| QA repair rounds (base) | {max_repairs} |
| QA repair rounds (hard cap after `repair --extend` justification) | {hard_cap} |
| Pre-QA rebuilds (no repair round consumed) | {pre_qa} |
| Parallel builder shards (tier-capped) | {max_builders} |

Delivery tiers (`quality_level`; legacy `basic` / `high-score` accepted as aliases):

| Tier | Calibration rounds | Shard cap | Blocks |
| --- | --- | --- | --- |
{tier_rows}

Delivery guarantee: every confirmed artifact is content-verified against the frozen
Slide Spec (PPTX/PDF page counts, per-page script sections) and hash-bound to its
final path under `outputs/` before `complete`.
{MARKER_END}"""


def apply_block(readme: Path, block: str) -> bool:
    text = readme.read_text(encoding="utf-8")
    pattern = re.compile(
        re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.DOTALL
    )
    if pattern.search(text):
        updated = pattern.sub(lambda _: block, text, count=1)
    else:
        updated = text.rstrip() + "\n\n" + block + "\n"
    if updated == text:
        return False
    readme.write_text(updated, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 2 on drift instead of writing")
    args = parser.parse_args(argv)
    contract = load_contract()
    drift = []
    for lang, path in READMES.items():
        block = render_block(contract, lang)
        if args.check:
            text = path.read_text(encoding="utf-8")
            if block not in text:
                drift.append(str(path))
        else:
            apply_block(path, block)
    if drift:
        print(
            "render_pipeline_tables: DRIFT — regenerate with scripts/render_pipeline_tables.py: "
            + ", ".join(drift),
            file=sys.stderr,
        )
        return 2
    if not args.check:
        print("render_pipeline_tables: README flow tables updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
