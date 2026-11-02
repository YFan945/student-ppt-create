#!/usr/bin/env python3
"""持久化演示文稿工作流状态，并管理确认门禁。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.hashing import file_sha256 as sha256_file  # noqa: E402

SEQUENCE = (
    "intake_pending",
    "intake_confirmed",
    "planned",
    "producing",
    "qa",
    "complete",
)
TERMINAL = {"incomplete", "blocked"}

# 返工边：qa 阶段发现 blocker 后回到 producing 重建，无需 reset 重跑
# 「confirm → 环境检查 → 规划」全流程。
# 恢复边：incomplete 补齐缺失门禁后回到 qa 重做交付检查。
REWORK_EDGES = {("qa", "producing"), ("incomplete", "qa")}

def project_root(cwd: Path | None = None) -> Path:
    """优先使用 CLAUDE_PROJECT_DIR，其次使用调用时的 cwd。"""
    configured = os.environ.get("CLAUDE_PROJECT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (cwd or Path.cwd()).resolve()


def default_state_file(cwd: Path | None = None, work_id: str | None = None) -> Path:
    work_id = work_id or os.environ.get("SP_WORK_ID")
    if not work_id or Path(work_id).name != work_id or work_id.startswith(".") or "/" in work_id or "\\" in work_id:
        raise SystemExit("Provide --work-id (or SP_WORK_ID); project-global workflow state is retired")
    return project_root(cwd) / "outputs" / ".pptx-work" / work_id / "workflow-state.json"


def load_state(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()  # noqa: UP017  # 环境无 datetime.UTC
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def transition_allowed(before: str, after: str) -> bool:
    if after in TERMINAL:
        return before not in {"intake_pending"} and before != after
    if (before, after) in REWORK_EDGES:
        return True
    if before not in SEQUENCE or after not in SEQUENCE:
        return False
    return SEQUENCE.index(after) == SEQUENCE.index(before) + 1


# Historical keyword diagnostics, retained for readers of old summaries only.
# They do not establish approval or block current confirmation.
SUMMARY_REQUIRED_GROUPS: dict[str, frozenset[str]] = {
    "场景": frozenset({"场景", "scenario"}),
    "受众": frozenset({"受众", "听众", "观众", "audience"}),
    "篇幅": frozenset({"页", "slide", "时长", "duration", "分钟", "min"}),
    "研究范围/证据": frozenset({"研究范围", "scope", "证据", "evidence", "来源"}),
    "输出/交付": frozenset({"输出", "output", "交付", "deliverable"}),
}


def summary_missing_groups(text: str) -> list[str]:
    """大小写不敏感的子串匹配；返回未覆盖的字段组名（有序）。"""
    lowered = text.lower()
    return [
        name
        for name, aliases in SUMMARY_REQUIRED_GROUPS.items()
        if not any(alias in lowered for alias in aliases)
    ]




def count_slides(pptx: Path) -> int | None:
    try:
        with zipfile.ZipFile(pptx) as archive:
            return sum(
                name.startswith("ppt/slides/slide") and name.endswith(".xml")
                for name in archive.namelist()
            )
    except (OSError, zipfile.BadZipFile):
        return None


def validate_completion_manifest(
    manifest_path: Path | None,
    pptx: Path | None,
    delivery_report_path: Path | None = None,
) -> list[str]:
    """Compatibility validation uses the current artifact, not old receipt fields."""
    del manifest_path, delivery_report_path
    from shared.artifact_validation import validate_artifact
    if pptx is None:
        return ["Provide --pptx for current artifact validation."]
    report = validate_artifact(pptx)
    if report["ok"]:
        return []
    issues = report.get("issues", []) + report.get("package", {}).get("findings", [])
    return [str(item.get("message") or item.get("detail") or item.get("code")) for item in issues
            if item.get("severity") not in {"info", "warning"}] or ["Actual artifact validation failed."]


def state_command(args: argparse.Namespace) -> int:
    work_id = getattr(args, "work_id", None) or os.environ.get("SP_WORK_ID")
    state_path = args.state_file or default_state_file(work_id=work_id)
    work_id = work_id or state_path.parent.name
    current = load_state(state_path)
    if current and current.get("work_id", work_id) != work_id:
        raise SystemExit("workflow state belongs to another work_id")

    if args.action == "show":
        if current is None:
            info = {"state": "missing", "path": str(state_path),
                    "hint": "运行 'init' 创建初始状态，或 'reset' 强制重置"}
        else:
            info = current
            info["state_file"] = str(state_path)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    if args.action == "init":
        if current is not None:
            print(
                f"⚠ 状态文件已存在（当前状态: {current.get('state')}）。"
                f"如需重新开始，请使用 'reset' 命令。",
                file=sys.stderr,
            )
            return 1
        save_state(
            state_path,
            {
                "workflow_version": "1.0",
                "work_id": work_id,
                "state": "intake_pending",
                "topic": args.topic,
                "summary_sha256": None,
            },
        )
        print(f"✅ 工作流状态已初始化（intake_pending）→ {state_path}")

    elif args.action == "reset":
        save_state(
            state_path,
            {
                "workflow_version": "1.0",
                "work_id": work_id,
                "state": "intake_pending",
                "topic": args.topic,
                "summary_sha256": None,
            },
        )
        print(f"✅ 工作流状态已重置为 intake_pending → {state_path}")

    elif args.action == "unblock":
        if not current:
            raise SystemExit(
                f"状态文件不存在，无需 unblock。请先运行 'init' 创建状态。\n"
                f"状态文件路径: {state_path}"
            )
        before = current.get("state")
        if before != "blocked":
            raise SystemExit(
                f"当前状态为 '{before}'，只有 'blocked' 状态才能 unblock。"
                f"如需强制重置，请使用 'reset' 命令。"
            )
        summary = Path(current.get("summary_file") or "")
        approved = summary.is_file() and sha256_file(summary) == current.get("summary_sha256")
        current["state"] = current.pop("resume_state", "intake_confirmed") if approved else "intake_pending"
        save_state(state_path, current)
        print(f"已恢复到 {current['state']} → {state_path}")

    elif args.action == "confirm":
        if not args.summary_file or not args.summary_file.is_file():
            raise SystemExit(
                f"摘要文件不存在: {args.summary_file}\n"
                f"请提供有效的 Production Summary 文件路径。"
            )
        try:
            summary_text: str | None = args.summary_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            summary_text = None  # 读取失败保持现有行为：不新增门禁，哈希照旧
        if summary_text is None or not summary_text.strip():
            raise SystemExit("Production Summary must be readable and nonempty.")
        # User approval applies to meaning; alias keywords cannot establish coverage.
        summary_hash = hashlib.sha256(args.summary_file.read_bytes()).hexdigest()
        base = current or {"workflow_version": "1.0", "topic": args.topic}
        base["work_id"] = work_id
        allowed_from = {None, "intake_pending"}
        if base.get("state") not in allowed_from:
            if not args.force:
                raise SystemExit(
                    f"无法从 '{base.get('state')}' 状态确认。"
                    f"当前状态必须是 intake_pending 或未初始化。"
                    f"如需需求变更后重新确认（保留当前进度），请加 --force。"
                )
            changed = base.get("summary_sha256") != summary_hash
            base["summary_file"] = str(args.summary_file.resolve())
            base["summary_sha256"] = summary_hash
            if changed:
                base["state"] = "intake_confirmed"
                for key in (
                    "rework_count",
                    "last_rework_reason",
                    "pptx_sha256",
                    "qa_manifest_sha256",
                    "delivery_report_sha256",
                ):
                    base.pop(key, None)
            save_state(state_path, base)
            action = "回退到 intake_confirmed" if changed else f"保留 {base.get('state')} 状态"
            print(f"✅ 已重新确认 Production Summary（{action}）→ {state_path}")
        else:
            base.update(
                {
                    "state": "intake_confirmed",
                    "summary_file": str(args.summary_file.resolve()),
                    "summary_sha256": summary_hash,
                }
            )
            save_state(state_path, base)
            print(f"✅ 状态已确认（intake_confirmed）→ {state_path}")

    elif args.action == "transition":
        if not current:
            raise SystemExit(
                f"工作流状态文件不存在。请先运行 'init' 创建状态。\n"
                f"状态文件路径: {state_path}"
            )
        before = str(current.get("state"))
        if args.to in TERMINAL:
            current["resume_state"] = before
        if not transition_allowed(before, args.to):
            valid_next = []
            try:
                idx = SEQUENCE.index(before)
                valid_next.append(SEQUENCE[idx + 1])
            except (ValueError, IndexError):
                pass
            if before == "qa":
                valid_next.append("producing")
            if before == "incomplete":
                valid_next.append("qa")
            if before != "intake_pending":
                valid_next.extend(sorted(TERMINAL))
            raise SystemExit(
                f"无效的状态转换: {before} → {args.to}\n"
                f"从 '{before}' 只能转换到: {', '.join(valid_next) if valid_next else '无法转换，请使用 reset'}"
            )
        if args.to == "complete":
            build = state_path.parent / "build-manifest.json"
            if build.is_file():
                from direct_production import complete
                result = complete(argparse.Namespace(work_dir=state_path.parent, review_note=None))
                print(json.dumps(result, ensure_ascii=False))
                return 0 if result["ok"] else 2
            # 轻量防线：complete 必须基于已确认且未变更的 Production Summary。
            summary_file = current.get("summary_file")
            summary_hash = current.get("summary_sha256")
            if not summary_file or not summary_hash:
                raise SystemExit(
                    "转换到 complete 必须已确认 Production Summary（运行 "
                    "'confirm --summary-file <summary>'）。"
                )
            current_summary = Path(str(summary_file))
            if (
                not current_summary.is_file()
                or hashlib.sha256(current_summary.read_bytes()).hexdigest() != summary_hash
            ):
                raise SystemExit(
                    "Production Summary 已变更或缺失，请重新运行 "
                    "'confirm --summary-file <summary>'（需求变更可加 --force）后再 complete。"
                )
            errors = validate_completion_manifest(
                args.qa_manifest,
                args.pptx,
                args.delivery_report,
            )
            if errors:
                raise SystemExit("无法完成交付：\n- " + "\n- ".join(errors))
        current["state"] = args.to
        if before == "qa" and args.to == "producing":
            current["rework_count"] = current.get("rework_count", 0) + 1
            current["last_rework_reason"] = args.reason
        save_state(state_path, current)
        print(f"✅ 状态转换: {before} → {args.to}")

    print(json.dumps(load_state(state_path), ensure_ascii=False, indent=2))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="管理 Student Presentation 工作流状态",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    for name in ("init", "show", "reset"):
        command = sub.add_parser(name, help={
            "init": "初始化状态为 intake_pending",
            "show": "显示当前状态",
            "reset": "强制重置状态为 intake_pending（丢弃当前进度）",
        }[name])
        command.add_argument("--state-file", type=Path, help="状态文件路径")
        command.add_argument("--topic", help="演示文稿主题")

    unblock = sub.add_parser(
        "unblock",
        help="恢复已确认任务；仅摘要缺失或改变时需要重新确认",
    )
    unblock.add_argument("--state-file", type=Path, help="状态文件路径")

    confirm = sub.add_parser("confirm", help="确认 Production Summary")
    confirm.add_argument("--state-file", type=Path, help="状态文件路径")
    confirm.add_argument("--topic", help="演示文稿主题")
    confirm.add_argument(
        "--summary-file", type=Path, required=True,
        help="Production Summary 文件路径",
    )
    confirm.add_argument(
        "--force", action="store_true",
        help="从非 intake_pending 状态重新确认；摘要变化时回退到 intake_confirmed",
    )

    transition = sub.add_parser("transition", help="推进工作流状态")
    transition.add_argument("--state-file", type=Path, help="状态文件路径")
    transition.add_argument(
        "--to",
        choices=(*SEQUENCE[2:], *sorted(TERMINAL)),
        required=True,
        help=f"目标状态（正向: {', '.join(SEQUENCE[2:])}；终态: {', '.join(sorted(TERMINAL))}）",
    )
    transition.add_argument(
        "--reason",
        type=str,
        help="optional note describing an actual correction",
    )
    transition.add_argument("--qa-manifest", type=Path, help="deprecated compatibility input; current artifact is validated")
    transition.add_argument(
        "--delivery-report",
        type=Path,
        help="deprecated compatibility input; current production owns completion",
    )
    transition.add_argument("--pptx", type=Path, help="转换到 complete 所需的交付 PPTX")

    for command in sub.choices.values():
        command.add_argument("--work-id", help="Isolated presentation work identifier")
    raise SystemExit(state_command(parser.parse_args()))


if __name__ == "__main__":
    main()
