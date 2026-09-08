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


def default_state_file(cwd: Path | None = None) -> Path:
    return project_root(cwd) / "outputs" / ".student-presentation-state.json"


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


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    if pptx is None:
        return ["转换到 complete 必须提供 --pptx 和 --delivery-report。"]
    if manifest_path is None:
        if delivery_report_path is None:
            return ["转换到 complete 必须提供 --pptx 和 --delivery-report。"]
        try:
            delivery = json.loads(delivery_report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"无法读取简化交付报告: {exc}"]
        if not isinstance(delivery, dict):
            return ["简化交付报告根节点必须是对象。"]
        slide_count = count_slides(pptx)
        errors = []
        if delivery.get("gate_profile") != "simplified-v1":
            errors.append("缺少 QA manifest 时必须使用 simplified-v1 交付报告。")
        if delivery.get("ok") is not True or delivery.get("status") != "complete":
            errors.append("简化交付报告未通过。")
        if not pptx.is_file() or delivery.get("pptx_sha256") != sha256_file(pptx):
            errors.append("简化交付报告与当前 PPTX 不一致。")
        if delivery.get("slide_spec_validation_passed") is not True:
            errors.append("Slide Spec 规划门禁未通过。")
        if delivery.get("package_validation_passed") is not True or delivery.get("package_blockers") != 0:
            errors.append("PPTX package validation 未通过。")
        if delivery.get("visual_reviewed") is not True:
            errors.append("未确认完成全页视觉检查。")
        if delivery.get("generation_core_version") != "0.7.1":
            errors.append("当前 sp-deck 简化交付必须使用 generation_core_version=0.7.1。")
        if delivery.get("actual_content_check_passed") is not True:
            errors.append("Actual Artifact readback 未通过。")
        if delivery.get("quality_check_passed") is not True:
            errors.append("v0.7.1 quality gate 未通过。")
        for hash_key, label in (
            ("quality_report_sha256", "quality report"),
            ("slide_spec_sha256", "frozen Slide Spec"),
            ("spec_lock_sha256", "Slide Spec lock"),
        ):
            value = delivery.get(hash_key)
            if not isinstance(value, str) or len(value) != 64:
                errors.append(f"简化交付报告缺少有效的 {label} hash。")
        if slide_count is None or delivery.get("preview_page_coverage") != f"{slide_count}/{slide_count}":
            errors.append("渲染预览未覆盖全部页面。")
        return errors
    errors: list[str] = []
    if delivery_report_path is None:
        errors.append("转换到 complete 必须提供 --delivery-report。")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"无法读取 QA manifest: {exc}"]
    if not isinstance(manifest, dict) or not pptx.is_file():
        return ["QA manifest 或 PPTX 无效。"]
    slide_count = count_slides(pptx)
    if manifest.get("pptx_sha256") != sha256_file(pptx):
        errors.append("QA manifest 的 pptx_sha256 与当前 PPTX 不一致。")
    if slide_count is None or manifest.get("slide_count") != slide_count:
        errors.append("QA manifest 的 slide_count 与 PPTX 不一致。")
    rendered = manifest.get("rendered_page_count")
    if rendered != slide_count:
        errors.append("QA manifest 的 rendered_page_count 与 PPTX 不一致。")
    if manifest.get("scenario_contract_passed") is not True:
        errors.append("QA manifest 未通过 scenario contract。")
    inspection = manifest.get("visual_inspection")
    if not isinstance(inspection, dict) or inspection.get("completed") is not True:
        errors.append("转换到 complete 必须完成逐页 visual_inspection。")
    elif inspection.get("remaining_blockers") != 0:
        errors.append("QA manifest 仍有未解决 blocker。")
    for report_key, hash_key, label in (
        ("content_qa_report", "content_qa_report_sha256", "content QA"),
        ("visual_inspection_report", "visual_inspection_report_sha256", "visual inspection"),
        ("asset_manifest", "asset_manifest_sha256", "asset manifest"),
        ("asset_manifest_report", "asset_manifest_report_sha256", "asset manifest validation"),
    ):
        report_value = manifest.get(report_key)
        if not report_value:
            errors.append(f"转换到 complete 缺少 {label} 报告。")
            continue
        report_path = Path(str(report_value))
        if not report_path.is_file() or manifest.get(hash_key) != sha256_file(report_path):
            errors.append(f"QA manifest 的 {label} 报告绑定无效。")
    if delivery_report_path is None:
        return errors
    try:
        delivery = json.loads(delivery_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"无法读取严格交付报告: {exc}")
        return errors
    if not isinstance(delivery, dict):
        errors.append("严格交付报告根节点必须是对象。")
        return errors
    if delivery.get("ok") is not True or delivery.get("status") != "complete":
        errors.append("严格交付报告未通过，不能转换到 complete。")
    if delivery.get("pptx_sha256") != sha256_file(pptx):
        errors.append("严格交付报告与当前 PPTX 不一致。")
    if delivery.get("qa_manifest_sha256") != sha256_file(manifest_path):
        errors.append("严格交付报告与当前 QA manifest 不一致。")
    if delivery.get("package_blockers") != 0:
        errors.append("严格交付报告仍包含 package validation blocker。")
    if delivery.get("package_validation_passed") is not True:
        errors.append("严格交付报告未通过 PPTX package validation。")
    coverage = delivery.get("preview_page_coverage")
    if coverage != f"{slide_count}/{slide_count}":
        errors.append("严格交付报告未覆盖全部渲染页面。")
    return errors


def state_command(args: argparse.Namespace) -> int:
    state_path = args.state_file or default_state_file()
    current = load_state(state_path)

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
        # unblock 必须重新走确认门禁，不能留在无 hash 的 intake_confirmed。
        current["state"] = "intake_pending"
        current["summary_sha256"] = None
        save_state(state_path, current)
        print(
            f"✅ 状态已从 blocked 恢复到 intake_pending → {state_path}\n"
            f"⚠ 注意：您需要重新确认 Production Summary 后才能继续生产。"
        )

    elif args.action == "confirm":
        if not args.summary_file or not args.summary_file.is_file():
            raise SystemExit(
                f"摘要文件不存在: {args.summary_file}\n"
                f"请提供有效的 Production Summary 文件路径。"
            )
        summary_hash = hashlib.sha256(args.summary_file.read_bytes()).hexdigest()
        base = current or {"workflow_version": "1.0", "topic": args.topic}
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
        is_rework = (before == "qa" and args.to == "producing") or (
            before == "incomplete" and args.to == "qa"
        )
        if is_rework and not args.reason:
            raise SystemExit("返工/恢复必须提供 --reason 记录 blocker 摘要")
        if before == "qa" and args.to == "producing" and current.get("rework_count", 0) >= 1:
            raise SystemExit("只允许一次完整重建返工；修复后仍有 blocker 时必须转为 incomplete。")
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
        help="从 blocked 状态恢复到 intake_pending，并重新确认摘要",
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
        help="返工 blocker 摘要（qa→producing 时必填）",
    )
    transition.add_argument("--qa-manifest", type=Path, help="转换到 complete 所需的 QA manifest")
    transition.add_argument(
        "--delivery-report",
        type=Path,
        help="转换到 complete 所需的交付报告；默认 simplified-v1，旧流程可配合 QA manifest",
    )
    transition.add_argument("--pptx", type=Path, help="转换到 complete 所需的交付 PPTX")

    raise SystemExit(state_command(parser.parse_args()))


if __name__ == "__main__":
    main()
