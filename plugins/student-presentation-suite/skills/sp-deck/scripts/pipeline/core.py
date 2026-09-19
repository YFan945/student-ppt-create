from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


ROOT = HERE.parents[2]
PPTX_TOOL = ROOT / "scripts" / "pptx_tool.py"
BUILDER = ROOT / "scripts" / "run_with_pptxgenjs.js"
EVIDENCE_COMPILER = ROOT / "scripts" / "research_pack_to_evidence.py"
CONTRACT_PATH = ROOT / "references" / "pipeline-contract.json"
MANIFEST_NAME = "build-manifest.json"


class RefusedError(Exception):
    """The pipeline refused an illegal or stale operation."""


def load_contract() -> dict[str, Any]:
    try:
        value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RefusedError(f"pipeline contract unavailable: {exc}") from exc
    if not isinstance(value, dict):
        raise RefusedError("pipeline contract root must be an object")
    return value


CONTRACT = load_contract()
MANIFEST_VERSION = str(CONTRACT.get("manifest_version") or "1.1")
MAX_REPAIRS = int(CONTRACT.get("max_repairs") or 3)
# 提额上限：`repair --extend` 可以在 base budget 之上追加轮次，但不能无界追加。
# 没有这个机制时，超预算的唯一出路是改已安装插件里的 pipeline-contract.json（2026-09-17
# live 就是这么做的）——升级即失效、不可审计，也违反"You never write into the installed
# plugin"。上限本身来自契约，所以仍然是一处定义。
MAX_REPAIRS_HARD_CAP = max(MAX_REPAIRS, int(CONTRACT.get("max_repairs_hard_cap") or 6))
# 确定性预检（pre-QA）轮次上限：`rendered` / `actual_content` 两道门只读 PPTX 本身、
# 不依赖 critic 产物，所以在 build 打包完成后立即运行。失败意味着"生成时就该做对的事
# 没做对"——这类问题走 builder 改页 + 重建，不消耗 repair 预算（省掉的是 render 和一整
# 轮 critic + QA）；连续失败超过这个轮数说明盲修在进行，剩余问题转正式 QA 流程计费。
MAX_PRE_QA_REBUILDS = max(1, int(CONTRACT.get("max_pre_qa_rebuilds") or 2))
# 并行 builder：墙钟 ≈ 回合数 × 每个回合的往返延迟（2026-09-18 实测：519 个回合里每个
# 只带 ~1.0 个工具调用，门本身只花 150 秒 = 全程的 1.7%）。既然串行是墙钟的唯一来源，
# 把页面拆给几个隔离 builder 同时做就是唯一不依赖模型改行为的墙钟杠杆——每个 builder
# 有独立的上下文与回合序列，13 页拆 3 份就把构建阶段的墙钟压到约 1/3，且不损失任何门。
# 少于这个页数时不拆：一个 builder 更快也更省（启动与读取的开销不划算）。
PARALLEL_MIN_PAGES = max(2, int(CONTRACT.get("parallel_builder_min_pages") or 4))
MAX_PARALLEL_BUILDERS = max(1, int(CONTRACT.get("max_parallel_builders") or 3))
QA_ORDER = tuple(CONTRACT.get("qa_order") or ("package", "rendered", "actual_content", "quality", "delivery"))
# QA 门分两类，这个区分决定了循环能不能提前停。
#
# 产物可用性门回答"这个 PPTX 本身能不能用"：包结构非法或渲染证据缺失时，后续门读不到
# 有效输入，结论没有意义 → 失败即停。
#
# 内容质量门（actual_content / quality / delivery）各自独立地读 PPTX、spec 和上游报告，
# 必须**全部跑完再汇总**。2026-09-18 复盘：原先的 fail-fast 让每轮 repair 只能看到一层门
# 的问题，6 轮 repair 恰好等于门的逐层暴露（轴 → claim → 来源区 → notes/配色 → 视觉），
# 累计约 199M token，占该次会话总消耗的 60%。
QA_HARD_STOP_STAGES = ("package", "rendered")
# delivery 只是把上游报告的结论汇总成一个交付状态；上游已经失败时它的失败没有增量信息，
# 记为派生（保留在报告里，但不计入 blocker），否则 repair 会被指向一个没有独立问题的地方。
QA_DERIVED_AFTER_UPSTREAM_FAILURE = ("delivery",)
GATE_HISTORY_NAME = "gate-history.json"
BUILD_FROM = {"planned", "producing"}
QA_FROM = {"producing", "qa"}
# A builder that looks at the rendered artifact after building will always find one more
# adjustment. Refusing the rebuild strands it: 2026-09-18 live, an entire repair round existed
# only to carry two pages' tweaks into the pptx ("第 3 轮：把 p6/p8 排版微调带入产物"), because
# the edits were made after the round's single allowed build. One carry-over rebuild per round
# closes that gap without opening an unbounded edit->build loop that would sidestep the budget.
MAX_CARRYOVER_BUILDS = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()


def manifest_path(work_dir: Path) -> Path:
    return work_dir / MANIFEST_NAME


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def load_manifest(work_dir: Path) -> dict[str, Any] | None:
    return load_json(manifest_path(work_dir))


def save_manifest(work_dir: Path, manifest: dict[str, Any]) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = now()
    manifest_path(work_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def require_state(manifest: dict[str, Any] | None, allowed: set[str], action: str) -> None:
    current = (manifest or {}).get("state") or "(absent)"
    if current not in allowed:
        raise RefusedError(
            f"{action} requires state in {sorted(allowed)}, but manifest is '{current}'"
        )


def bind(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256_file(path)}


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def pptx_path(manifest: dict[str, Any]) -> Path:
    return Path(str(((manifest.get("build") or {}).get("pptx") or {}).get("path") or ""))


def render_is_current(manifest: dict[str, Any]) -> bool:
    """Render evidence is only valid for the PPTX hash it was produced from.

    `build` clears manifest['render'], so a rebuilt deck can never claim the
    previous contact sheet. Existence of a PNG on disk is not evidence.
    """
    render = manifest.get("render") or {}
    recorded = str(render.get("pptx_sha256") or "")
    if not recorded:
        return False
    pptx = pptx_path(manifest)
    if not pptx.is_file() or recorded != sha256_file(pptx):
        return False
    contact = Path(str((render.get("contact_sheet") or {}).get("path") or ""))
    pages = [Path(str(item.get("path"))) for item in render.get("pages") or []]
    if not contact.is_file() or not pages:
        return False
    return all(binding_is_current(item) for item in [render["contact_sheet"], *render["pages"]])


def archive_stale_render(work_dir: Path, manifest: dict[str, Any]) -> list[str]:
    """Move the previous build's render evidence out of the canonical paths.

    Files are kept under `stale/render-<sha8>/` for audit. Leaving them at
    `contact-sheet.png` / `render/` made a rebuilt deck look already rendered,
    so a repaired deck could be visually reviewed against the old images.
    """
    render = manifest.get("render") or {}
    candidates: list[Path] = []
    contact = (render.get("contact_sheet") or {}).get("path")
    if contact:
        candidates.append(Path(str(contact)))
    thumb = (render.get("contact_sheet_thumb") or {}).get("path")
    if thumb:
        candidates.append(Path(str(thumb)))
    candidates.extend(Path(str(item.get("path"))) for item in render.get("pages") or [])
    existing = [path for path in candidates if path.is_file()]
    if any(not path.resolve().is_relative_to(work_dir.resolve()) for path in existing):
        raise RefusedError("render archive cannot move files outside work-dir")
    if not existing:
        return []
    label = str(render.get("pptx_sha256") or "unknown")[:8]
    target = work_dir / "stale" / f"render-{label}"
    target.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for path in existing:
        destination = target / path.name
        if destination.exists():
            destination.unlink()
        shutil.move(str(path), str(destination))
        moved.append(str(destination))
    return moved


def write_stage_summary(work_dir: Path, state: str, lines: list[str]) -> Path:
    """CD-4: the pipeline writes the ≤30-line stage entry, not the model."""
    path = work_dir / f"stage-{state}-summary.md"
    body = [f"# stage-{state}", ""]
    for line in lines:
        if line is None:
            continue
        body.append(line)
        if len(body) >= 32:
            break
    body.append("")
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def record(manifest: dict[str, Any], command: str, before: str, after: str, **extra: Any) -> None:
    manifest.setdefault("history", []).append(
        {"at": now(), "command": command, "from": before, "to": after, **extra}
    )


def default_workflow_state(work_dir: Path) -> Path:
    return work_dir.resolve() / "workflow-state.json"


def validate_work_dir(work_dir: Path) -> None:
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
    allowed = project / "outputs" / ".pptx-work"
    resolved = work_dir.resolve()
    if resolved.parent != allowed.resolve() or resolved.name.startswith("."):
        raise RefusedError(f"work-dir must be outputs/.pptx-work/<work-id> under {project}")
    if resolved.is_relative_to(ROOT.resolve()) or (ROOT.parents[1] / ".claude-plugin/marketplace.json").is_file() and resolved.is_relative_to(ROOT.parents[1]):
        raise RefusedError("work-dir must not be inside the installed plugin or marketplace repository")


def validate_intake(state_path: Path) -> dict[str, Any]:
    state = load_json(state_path)
    if not state:
        raise RefusedError(
            f"intake state missing: {state_path}; run workflow_guard.py init/confirm first"
        )
    if state.get("state") != "intake_confirmed":
        raise RefusedError(
            f"plan requires workflow state intake_confirmed, got {state.get('state')!r}"
        )
    summary_file = Path(str(state.get("summary_file") or ""))
    summary_sha = str(state.get("summary_sha256") or "")
    if not summary_file.is_file() or not summary_sha:
        raise RefusedError("confirmed workflow state has no valid Production Summary binding")
    if sha256_file(summary_file) != summary_sha:
        raise RefusedError("Production Summary changed after confirmation; confirm it again")
    return state


def validate_manifest_authorization(manifest: dict[str, Any]) -> None:
    workflow = manifest.get("workflow") or {}
    state_path = Path(str(workflow.get("state_file") or ""))
    summary_path = Path(str(workflow.get("summary_file") or ""))
    summary_sha = str(workflow.get("summary_sha256") or "")
    if not state_path.is_file() or not summary_path.is_file() or not summary_sha:
        raise RefusedError("manifest has no valid intake authorization binding; re-plan")
    if sha256_file(summary_path) != summary_sha:
        raise RefusedError("Production Summary changed after plan; re-confirm and re-plan")
    state = load_json(state_path) or {}
    if state.get("work_id") != manifest.get("work_id") or state.get("summary_sha256") != summary_sha:
        raise RefusedError("workflow work_id or confirmed summary no longer matches manifest")
    if state.get("state") != manifest.get("state"):
        raise RefusedError("workflow authorization was reset or revoked; re-confirm and re-plan")
    source = manifest.get("source")
    if source and not binding_is_current(source):
        raise RefusedError("source deck changed after plan; restore source or re-confirm and re-plan")
    if any(not binding_is_current(item) for item in (manifest.get("inputs") or {}).values()):
        raise RefusedError("planned input changed or disappeared; re-plan")
    research = manifest.get("research") or {}
    research_execution = research.get("execution")
    if research and research_execution is not None and not binding_is_current(research_execution):
        raise RefusedError("research execution receipt changed after plan")


def binding_is_current(binding: dict[str, Any]) -> bool:
    path = Path(str(binding.get("path") or ""))
    return path.is_file() and binding.get("sha256") == sha256_file(path)


def execution_receipt(
    work_dir: Path, role: str, artifact: Path, *, policy: str = "require",
) -> dict[str, Any]:
    """Hook-owned isolated-run receipt; policy="allow-missing" degrades openly.

    A receipt that EXISTS but fails its binding checks stays a hard refusal.
    Only a MISSING receipt can degrade, because the reason it is missing sits
    with the runtime, not the model: 2026-09-19 live, ZCode never delivered
    SubagentStart/SubagentStop to plugin hooks, so the receipt could not exist
    and `plan` hard-refused — the session then burned 52 requests (~50% of the
    whole run, 6.5M input tokens) reverse-engineering the gate and abandoned
    the pipeline for a hand-rolled build with no gates at all.
    """
    receipt_path = work_dir / f"{role}-execution.json"
    expected = "presentation-researcher" if role == "research" else "visual-critic"
    # Existence first: a PRESENT-but-empty/corrupt receipt file must not pass as
    # "missing" under allow-missing — only a truly absent file can degrade
    # (2026-09-20 review: load_json(...)" or {}" conflated the two).
    if not receipt_path.is_file():
        if policy == "allow-missing":
            return {
                "agent": f"student-presentation-suite:{expected}",
                "spawn_verified": False,
                "degraded": "receipt-missing-allowed",
                "work_id": work_dir.name,
                "artifact": bind(artifact),
                "reads": {},
            }
        raise RefusedError(
            f"missing successful isolated {role} runtime receipt (hook-owned: "
            "runtime_evidence.py writes it at SubagentStop; the model cannot write it). "
            "Run doctor --work-dir <wd> to check whether this runtime delivers subagent "
            "hook events; if it does not, re-run plan/qa with --receipt-policy allow-missing"
        )
    receipt = load_json(receipt_path) or {}
    if receipt.get("agent") != f"student-presentation-suite:{expected}" or not receipt.get("agent_id") or receipt.get("spawn_verified") is not True or receipt.get("work_id") != work_dir.name:
        raise RefusedError(
            f"invalid isolated {role} runtime receipt at {receipt_path} (present but "
            "empty, corrupt or identity-mismatched) — a present receipt can never "
            "degrade via --receipt-policy allow-missing; it must be re-issued by the "
            "hook or removed together with the work-dir"
        )
    if receipt.get("artifact") != bind(artifact):
        raise RefusedError(
            f"{role} artifact changed after isolated execution — if this was an "
            "authorized gap-fill, resume the SAME researcher via SendMessage (its next "
            "SubagentStop refreshes the receipt) or run a zero-search recheck researcher "
            "to re-issue it; do not edit the pack from the main session"
        )
    return receipt


def work_id_receipt_policy(manifest: dict[str, Any] | None) -> str:
    """Receipt policy as work-id state; later stages inherit it (2026-09-20 review).

    Once plan ran with --receipt-policy allow-missing, every later stage of THIS
    work-id inherits the decision — an agent following next_command verbatim must
    not re-hit the receipt refusal just because it forgot a flag. A prior
    degraded QA counts too, so repair loops after a degraded QA stay degraded.
    """
    if not manifest:
        return "require"
    if (manifest.get("research") or {}).get("receipt_policy") == "allow-missing":
        return "allow-missing"
    if (manifest.get("qa") or {}).get("critic_receipt") == "missing-allowed":
        return "allow-missing"
    return "require"


def mirror_workflow_state(manifest: dict[str, Any], state: str, *, reason: str | None = None) -> None:
    workflow = manifest.get("workflow") or {}
    path = Path(str(workflow.get("state_file") or ""))
    current = load_json(path)
    if not current:
        raise RefusedError(f"workflow state disappeared after plan: {path}")
    if current.get("work_id") != manifest.get("work_id"):
        raise RefusedError("cannot mirror another work_id's authorization")
    current["state"] = state
    current["updated_at"] = now()
    current["pipeline_manifest"] = str(manifest_path(Path(str(manifest.get("work_dir") or "."))))
    current["pipeline_manifest_version"] = MANIFEST_VERSION
    if reason:
        current["last_pipeline_reason"] = reason
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def generator_files(entry: Path) -> list[Path]:
    pages_dir = entry.parent / "pages"
    pages = sorted(pages_dir.glob("*.js")) if pages_dir.is_dir() else []
    return [entry, *pages]


def generator_fingerprint(entry: Path) -> tuple[str, list[dict[str, Any]]]:
    files = generator_files(entry)
    bindings = [bind(path) for path in files]
    return stable_hash([(item["path"], item["sha256"]) for item in bindings]), bindings


def qa_input_fingerprint(
    pptx: Path,
    visual_review: Path | None,
    notes: Path | None,
    previews: list[Path],
) -> str:
    values: list[tuple[str, str | None]] = [("pptx", sha256_file(pptx))]
    for label, path in (("visual_review", visual_review), ("notes", notes)):
        values.append((label, sha256_file(path) if path and path.is_file() else None))
    values.extend((f"preview:{path.resolve()}", sha256_file(path)) for path in previews if path.is_file())
    return stable_hash(values)


@dataclass
class Stage:
    name: str
    argv: list[str]
    report: Path
    artifact: str
    issues_key: str = "issues"


def _gate_inputs(manifest: dict[str, Any]) -> dict[str, str]:
    """The gate input map shared by the QA and pre-QA stage builders."""
    inputs = manifest.get("inputs") or {}
    build = manifest.get("build") or {}
    return {
        "pptx": str((build.get("pptx") or {}).get("path") or ""),
        "slide_spec": str((inputs.get("slide_spec") or {}).get("path") or ""),
        "spec_lock": str((inputs.get("spec_lock") or {}).get("path") or ""),
        "art_direction": str((inputs.get("art_direction") or {}).get("path") or ""),
        "visual_generation_report": str((inputs.get("visual_generation_report") or {}).get("path") or ""),
        "slide_spec_report": str((inputs.get("slide_spec_report") or {}).get("path") or ""),
    }


def _gate_stage(
    name: str,
    work_dir: Path,
    report_prefix: str,
    gate_inputs: dict[str, str],
    *,
    visual_review: Path | None = None,
    notes: Path | None = None,
    previews: list[Path] | None = None,
    allow_missing_preview: bool = False,
) -> Stage:
    """Build ONE gate stage from ONE place (Batch 5 gate registry).

    `references/pipeline-contract.json#qa_gates` documents each gate's script,
    phase, requirements and dependencies; this function is the single execution
    of that registry — the QA run and the pre-QA subset share it, so an argument
    change can never be applied to one run and forgotten in the other.
    """
    registry = CONTRACT.get("qa_gates") or {}
    entry = registry.get(name) or {}
    artifact = str(entry.get("artifact") or name)
    stage_name = name.replace("_", "-")
    report = work_dir / f"{report_prefix}-{stage_name}.json"

    def gate(script: str, *args: str) -> list[str]:
        return [sys.executable, str(HERE / script), *args]

    pptx = gate_inputs.get("pptx") or ""
    spec = gate_inputs.get("slide_spec") or ""
    lock = gate_inputs.get("spec_lock") or ""
    art = gate_inputs.get("art_direction") or ""
    vgr = gate_inputs.get("visual_generation_report") or ""
    spec_report = gate_inputs.get("slide_spec_report") or ""

    if name == "package":
        argv = [sys.executable, str(PPTX_TOOL), "validate", pptx, "--output", str(report)]
    elif name == "rendered":
        argv = gate("pptx_rendered_check.py", "--pptx", pptx, "--output", str(report))
    elif name == "actual_content":
        argv = gate("pptx_actual_content_check.py", pptx, spec, "--output", str(report))
    elif name == "quality":
        # `visual_review` decides full (post-critic) vs deterministic (pre-build) half.
        argv = gate("pptx_quality_gate_v071.py", "--pptx", pptx, "--slide-spec", spec,
                    "--spec-lock", lock, "--output", str(report))
        if visual_review:
            argv += ["--visual-report", str(visual_review)]
    elif name == "delivery":
        argv = gate(
            "pptx_delivery_check_v08.py",
            "--pptx", pptx, "--slide-spec", spec, "--spec-lock", lock,
            "--art-direction", art, "--visual-generation-report", vgr,
            "--quality-report", str(work_dir / "qa-quality.json"),
            "--package-report", str(work_dir / "qa-package.json"),
            "--slide-spec-report", spec_report,
            "--actual-content-report", str(work_dir / "qa-actual-content.json"),
            "--visual-reviewed", "--visual-review-report", str(visual_review),
            "--output", str(report),
        )
        if notes:
            argv += ["--notes", str(notes)]
        for preview in previews or []:
            argv += ["--preview", str(preview)]
        if allow_missing_preview:
            argv.append("--allow-missing-preview")
    else:  # pragma: no cover - registry and this switch must move together
        raise RefusedError(f"gate {name} has no stage builder (update _gate_stage + qa_gates)")
    return Stage(stage_name, argv, report, artifact)


def build_qa_stages(
    manifest: dict[str, Any],
    work_dir: Path,
    *,
    visual_review: Path | None,
    notes: Path | None = None,
    previews: list[Path] | None = None,
    allow_missing_preview: bool = False,
) -> list[Stage]:
    gate_inputs = _gate_inputs(manifest)
    pptx = gate_inputs["pptx"]
    spec = gate_inputs["slide_spec"]
    lock = gate_inputs["spec_lock"]
    art = gate_inputs["art_direction"]
    vgr = gate_inputs["visual_generation_report"]
    spec_report = gate_inputs["slide_spec_report"]

    candidates: dict[str, Stage] = {
        "package": _gate_stage("package", work_dir, "qa", gate_inputs),
        "rendered": _gate_stage("rendered", work_dir, "qa", gate_inputs),
    }
    if spec:
        candidates["actual_content"] = _gate_stage("actual_content", work_dir, "qa", gate_inputs)
    if spec and lock and visual_review:
        candidates["quality"] = _gate_stage(
            "quality", work_dir, "qa", gate_inputs, visual_review=visual_review,
        )

    required = {
        "pptx": pptx, "slide-spec": spec, "spec-lock": lock, "art-direction": art,
        "visual-generation-report": vgr, "slide-spec-report": spec_report,
        "visual-review": str(visual_review or ""),
    }
    dependencies = {"package", "actual_content", "quality"}
    if not [name for name, value in required.items() if not value] and dependencies <= set(candidates):
        candidates["delivery"] = _gate_stage(
            "delivery", work_dir, "qa", gate_inputs,
            visual_review=visual_review, notes=notes, previews=previews,
            allow_missing_preview=allow_missing_preview,
        )

    return [candidates[name] for name in QA_ORDER if name in candidates]


def pre_qa_stages(manifest: dict[str, Any], work_dir: Path) -> list[Stage]:
    """The deterministic gates that need no critic, with their own pre-QA report paths.

    Reports go to pre-qa-*.json so they can be handed to the builder without
    being confused with (or silently overwritten by) the authoritative QA run
    that re-executes the same checks later. Stage construction goes through the
    SAME `_gate_stage` builder as the full QA run — only the report prefix and
    the critic inputs differ.
    """
    gate_inputs = _gate_inputs(manifest)
    if not gate_inputs["pptx"]:
        return []
    stages = [_gate_stage("rendered", work_dir, "pre-qa", gate_inputs)]
    if gate_inputs["slide_spec"]:
        stages.append(_gate_stage("actual_content", work_dir, "pre-qa", gate_inputs))
    if gate_inputs["slide_spec"] and gate_inputs["spec_lock"]:
        # Evidence closure, note timing and the spec lock are pure PPTX + spec reads — the
        # same pass the quality gate runs, minus everything that needs the critic. Without
        # this stage build #1 reports "0 blockers" and the deck goes to render + a full
        # critic pass before QA reveals deterministic misses (2026-09-18 live: 48 blockers
        # after a green pre-QA).
        stage = _gate_stage("quality", work_dir, "pre-qa", gate_inputs)
        stages.append(Stage("quality-deterministic", stage.argv, stage.report, stage.artifact))
    return stages


def run_pre_qa_gates(manifest: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    """Run the deterministic gates inside build, before any render or critic cost.

    2026-09-17 live: a missing planned number surfaced only at the QA stage —
    after render AND a full isolated critic pass had been paid for a deck that
    was already doomed. `rendered` / `actual_content` read the PPTX itself and
    need no critic output, so build runs them the moment the deck exists. A
    deterministic miss then costs one Edit + one local rebuild instead of a
    critic round; the critic only ever reviews a deck that already passes the
    deterministic gates.
    """
    stages = pre_qa_stages(manifest, work_dir)
    pptx = Path(str(((manifest.get("build") or {}).get("pptx") or {}).get("path") or ""))
    reports: dict[str, Any] = {}
    problems: list[dict[str, Any]] = []
    for stage in stages:
        ok, stage_problems, binding = collect(stage)
        reports[stage.artifact] = binding
        problems.extend(stage_problems)
    blockers = sum(1 for item in problems if item["severity"] in QA_BLOCKING_SEVERITIES)
    prior = manifest.get("pre_qa") or {}
    ok = bool(stages) and blockers == 0 and all(binding.get("ok") for binding in reports.values())
    return {
        "ok": ok,
        "blockers": blockers,
        "problems": problems,
        "stages": reports,
        "pptx_sha256": sha256_file(pptx) if pptx.is_file() else None,
        # consecutive failing builds; reset to 0 whenever the gates pass
        "rounds": 0 if ok else int(prior.get("rounds") or 0) + 1,
        "max_rounds": MAX_PRE_QA_REBUILDS,
    }


def pre_qa_failed_current(manifest: dict[str, Any]) -> bool:
    """Whether the CURRENT build failed the pre-QA gates (and still may rebuild).

    The pptx binding in `build` is replaced by every build, so a stale pre_qa
    entry (from an earlier deck) can never unlock a rebuild by itself.
    """
    pre_qa = manifest.get("pre_qa") or {}
    build_sha = str(((manifest.get("build") or {}).get("pptx") or {}).get("sha256") or "")
    if not build_sha or pre_qa.get("pptx_sha256") != build_sha:
        return False
    if pre_qa.get("ok") is not False:
        return False
    return int(pre_qa.get("rounds") or 0) < MAX_PRE_QA_REBUILDS


def generator_changed_since_build(manifest: dict[str, Any]) -> bool:
    """Whether the generator files changed since the last recorded build.

    This is the deterministic "the builder came back and edited pages" signal: a
    rebuild is only meaningful once the fingerprint moves, and `cmd_build` refuses
    the no-op rebuild itself. With no recorded build there is nothing to compare
    against, so the answer is False — a first build must be dispatched through its
    own stage (calibration green + no scaffold stubs), never inferred from here.
    Edit-mode decks hash their OOXML tree, not a generator entry, so they never
    report a change here; their rebuild stays a main-session decision.
    """
    build_info = manifest.get("build") or {}
    previous = str(build_info.get("generator_fingerprint") or "")
    if not previous:
        return False
    entry = Path(str(build_info.get("entry") or ""))
    if not entry.is_file():
        return False
    try:
        fingerprint, _ = generator_fingerprint(entry)
    except Exception:
        return False
    return fingerprint != previous


# Calibration review logic moved to calibration_review.py (Batch 4.2) so the
# style-contract generator can reuse the same green check without a cycle.
from calibration_review import (  # noqa: E402
    QA_BLOCKING_SEVERITIES,
    normalise_severity,
)


def collect(stage: Stage) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
    started = time.monotonic()
    # A failed command must not inherit a previous run's successful report.
    stage.report.unlink(missing_ok=True)
    proc = _runner(stage.argv)
    duration_ms = int((time.monotonic() - started) * 1000)
    if not stage.report.is_file():
        detail = (proc.stderr or proc.stdout or "").strip()
        return False, [{
            "gate": stage.name, "severity": "critical",
            "code": f"{stage.name}_missing_report",
            "message": f"{stage.name} produced no report (exit {proc.returncode}): {detail[:200]}",
        }], {"ok": False, "checked": True, "exit_code": proc.returncode, "duration_ms": duration_ms}
    report = json.loads(stage.report.read_text(encoding="utf-8"))
    issues = report.get(stage.issues_key) if isinstance(report.get(stage.issues_key), list) else []
    problems = [{
        "gate": stage.name,
        "severity": normalise_severity(report, issue),
        "code": str(issue.get("code") or f"{stage.name}_issue"),
        "message": str(issue.get("message") or issue.get("detail") or issue.get("problem") or issue),
        **({"slide": issue.get("slide")} if issue.get("slide") is not None else {}),
    } for issue in issues if isinstance(issue, dict)]
    binding = {
        "ok": report.get("ok") is True and proc.returncode == 0, "checked": True,
        "exit_code": proc.returncode, "duration_ms": duration_ms,
        "issue_count": len(issues), **bind(stage.report),
    }
    if not binding["ok"] and not any(item["severity"] in {"critical", "major"} for item in problems):
        problems.append({
            "gate": stage.name, "severity": "major",
            "code": f"{stage.name}_failed",
            "message": f"{stage.name} reported not ok without itemised issues (exit {proc.returncode}).",
        })
    return binding["ok"], problems, binding


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        marker = (item["severity"], item["code"], str(item["message"]))
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result


def run_command(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv, check=False, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
_runner: Runner = run_command
