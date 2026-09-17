#!/usr/bin/env python3
"""sp-deck deterministic production pipeline.

The agent owns semantic and visual judgement. This CLI owns execution order,
state, rendering, idempotence, QA dependencies, repair budget, and delivery.
Production is driven by one build-manifest.json; the legacy workflow state is
used only as the intake authorization source and is mirrored automatically.

    plan      verify intake, freeze, preflight, scaffold pages/  -> planned
    build     run the generator; refuses unsplitted deck.js      -> producing
    render    raster pages + contact-sheet.png (hash-cached)
    qa        QA DAG: artifact gates stop, content gates all run -> qa
    repair    QA blockers -> producing (budget from contract)
    complete  qa + delivery ok                                   -> complete
    status    one-line manifest summary
    next      what to read and which command to run next

Exit codes: 0 = ok, 2 = refused (illegal state, failed gate, missing input).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
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

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import generator_scaffold as _scaffold  # noqa: E402

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
QA_BLOCKING_SEVERITIES = ("critical", "major")
GATE_HISTORY_NAME = "gate-history.json"
BUILD_FROM = {"planned", "producing"}
QA_FROM = {"producing", "qa"}


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
    if manifest.get("research") and not binding_is_current(manifest["research"]["execution"]):
        raise RefusedError("research execution receipt changed after plan")


def binding_is_current(binding: dict[str, Any]) -> bool:
    path = Path(str(binding.get("path") or ""))
    return path.is_file() and binding.get("sha256") == sha256_file(path)


def execution_receipt(work_dir: Path, role: str, artifact: Path) -> dict[str, Any]:
    receipt = load_json(work_dir / f"{role}-execution.json") or {}
    expected = "presentation-researcher" if role == "research" else "visual-critic"
    if receipt.get("agent") != f"student-presentation-suite:{expected}" or not receipt.get("agent_id") or receipt.get("spawn_verified") is not True or receipt.get("work_id") != work_dir.name:
        raise RefusedError(f"missing successful isolated {role} runtime receipt")
    if receipt.get("artifact") != bind(artifact):
        raise RefusedError(f"{role} artifact changed after isolated execution")
    return receipt


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


def build_qa_stages(
    manifest: dict[str, Any],
    work_dir: Path,
    *,
    visual_review: Path | None,
    notes: Path | None = None,
    previews: list[Path] | None = None,
    allow_missing_preview: bool = False,
) -> list[Stage]:
    inputs = manifest.get("inputs") or {}
    build = manifest.get("build") or {}
    pptx = str((build.get("pptx") or {}).get("path") or "")
    spec = str((inputs.get("slide_spec") or {}).get("path") or "")
    lock = str((inputs.get("spec_lock") or {}).get("path") or "")
    art = str((inputs.get("art_direction") or {}).get("path") or "")
    vgr = str((inputs.get("visual_generation_report") or {}).get("path") or "")
    spec_report = str((inputs.get("slide_spec_report") or {}).get("path") or "")

    def gate(script: str, *args: str) -> list[str]:
        return [sys.executable, str(HERE / script), *args]

    candidates: dict[str, Stage] = {
        "package": Stage(
            "package",
            [sys.executable, str(PPTX_TOOL), "validate", pptx, "--output", str(work_dir / "qa-package.json")],
            work_dir / "qa-package.json", "package",
        ),
        "rendered": Stage(
            "rendered",
            gate("pptx_rendered_check.py", "--pptx", pptx, "--output", str(work_dir / "qa-rendered.json")),
            work_dir / "qa-rendered.json", "rendered",
        ),
    }
    if spec:
        candidates["actual_content"] = Stage(
            "actual-content",
            gate("pptx_actual_content_check.py", pptx, spec, "--output", str(work_dir / "qa-actual-content.json")),
            work_dir / "qa-actual-content.json", "actual_content",
        )
    if spec and lock and visual_review:
        candidates["quality"] = Stage(
            "quality",
            gate(
                "pptx_quality_gate_v071.py", "--pptx", pptx, "--slide-spec", spec,
                "--spec-lock", lock, "--visual-report", str(visual_review),
                "--output", str(work_dir / "qa-quality.json"),
            ),
            work_dir / "qa-quality.json", "quality",
        )

    required = {
        "pptx": pptx, "slide-spec": spec, "spec-lock": lock, "art-direction": art,
        "visual-generation-report": vgr, "slide-spec-report": spec_report,
        "visual-review": str(visual_review or ""),
    }
    if not [name for name, value in required.items() if not value] and {
        "package", "actual_content", "quality"
    } <= set(candidates):
        argv = gate(
            "pptx_delivery_check_v08.py",
            "--pptx", pptx, "--slide-spec", spec, "--spec-lock", lock,
            "--art-direction", art, "--visual-generation-report", vgr,
            "--quality-report", str(work_dir / "qa-quality.json"),
            "--package-report", str(work_dir / "qa-package.json"),
            "--slide-spec-report", spec_report,
            "--actual-content-report", str(work_dir / "qa-actual-content.json"),
            "--visual-reviewed", "--visual-review-report", str(visual_review),
            "--output", str(work_dir / "qa-delivery.json"),
        )
        if notes:
            argv += ["--notes", str(notes)]
        for preview in previews or []:
            argv += ["--preview", str(preview)]
        if allow_missing_preview:
            argv.append("--allow-missing-preview")
        candidates["delivery"] = Stage(
            "delivery", argv, work_dir / "qa-delivery.json", "delivery"
        )

    return [candidates[name] for name in QA_ORDER if name in candidates]


def pre_qa_stages(manifest: dict[str, Any], work_dir: Path) -> list[Stage]:
    """The two deterministic gates, with their own pre-QA report paths.

    Reports go to pre-qa-*.json so they can be handed to the builder without
    being confused with (or silently overwritten by) the authoritative QA run
    that re-executes the same checks later.
    """
    inputs = manifest.get("inputs") or {}
    pptx = str(((manifest.get("build") or {}).get("pptx") or {}).get("path") or "")
    spec = str((inputs.get("slide_spec") or {}).get("path") or "")
    if not pptx:
        return []
    stages = [
        Stage(
            "rendered",
            [sys.executable, str(HERE / "pptx_rendered_check.py"), "--pptx", pptx,
             "--output", str(work_dir / "pre-qa-rendered.json")],
            work_dir / "pre-qa-rendered.json", "rendered",
        )
    ]
    if spec:
        stages.append(
            Stage(
                "actual-content",
                [sys.executable, str(HERE / "pptx_actual_content_check.py"), pptx, spec,
                 "--output", str(work_dir / "pre-qa-actual-content.json")],
                work_dir / "pre-qa-actual-content.json", "actual_content",
            )
        )
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


def normalise_severity(report: dict[str, Any], issue: dict[str, Any]) -> str:
    severity = str(issue.get("severity") or "").lower()
    if severity in {"critical", "major", "blocker"}:
        return "critical" if severity == "critical" else "major"
    if severity == "minor":
        return "minor"
    return "major" if not report.get("ok", True) else "minor"


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


def compile_research_for_plan(
    work_dir: Path, spec: Path, args: argparse.Namespace,
) -> tuple[Path, Path, Path, Path]:
    """Compile F/D/Q → evidence-map.json. Agents must not guess this CLI.

    2026-09-16 live run spent ~10 turns probing --evidence-map flags. Plan always
    compiles from pack + validation sitting in the work-dir (or explicit flags).
    """
    pack = (args.research_pack or work_dir / "research-pack.json").resolve()
    validation = (args.research_validation or work_dir / "research-pack-validation.json").resolve()
    missing = [label for label, path in (("research-pack.json", pack), ("research-pack-validation.json", validation)) if not path.is_file()]
    if missing:
        raise RefusedError(
            "research-backed plan needs "
            + " and ".join(missing)
            + f" in {work_dir} (or pass --research-pack / --research-validation). "
            "plan compiles evidence-map.json itself — do not invent --evidence-map."
        )
    evidence_map = work_dir / "evidence-map.json"
    compiled_spec = work_dir / f"slide-spec-compiled{spec.suffix}"
    compiled = _runner([
        sys.executable, str(EVIDENCE_COMPILER), str(pack),
        "--validation-report", str(validation),
        "--slide-spec", str(spec),
        "--compiled-slide-spec", str(compiled_spec),
        "--output", str(evidence_map),
    ])
    if compiled.returncode != 0 or not evidence_map.is_file():
        detail = (compiled.stderr or compiled.stdout or "").strip()
        raise RefusedError(f"evidence compile failed (exit {compiled.returncode}): {detail[:400]}")
    if compiled_spec.is_file():
        spec = compiled_spec
    return spec, pack, validation, evidence_map.resolve()


def cmd_plan(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    if not args.force:
        require_state(manifest, {"(absent)", "planned"}, "plan")
    if manifest and manifest.get("state") == "planned" and not args.force:
        raise RefusedError("already planned; pass --force to re-plan")

    workflow_state_path = (args.workflow_state or default_workflow_state(work_dir)).resolve()
    intake = validate_intake(workflow_state_path)
    if workflow_state_path != default_workflow_state(work_dir) or intake.get("work_id") != work_dir.name:
        raise RefusedError("intake must belong to this work_id and use its workflow-state.json")

    spec = args.slide_spec.resolve()
    validation_report = args.validation_report.resolve()
    art = args.art_direction.resolve()
    for label, path in (("Slide Spec", spec), ("validation report", validation_report), ("Art Direction", art)):
        if not path.is_file():
            raise RefusedError(f"{label} does not exist: {path}")
    import yaml

    sys.path.insert(0, str(ROOT / "scripts"))
    from slide_spec_to_pptx_brief import derive_production_mode, validate_production_source

    spec_data = yaml.safe_load(spec.read_text(encoding="utf-8"))
    if not isinstance(spec_data, dict):
        raise RefusedError("Slide Spec must be an object")
    if spec_data.get("source_deck"):
        source = Path(spec_data["source_deck"]).expanduser()
        spec_data["source_deck"] = str((spec.parent / source).resolve())
    try:
        mode = derive_production_mode(spec_data, getattr(args, "production_mode", None))
        validate_production_source(spec_data, mode)
    except ValueError as exc:
        raise RefusedError(str(exc)) from exc
    work_dir.mkdir(parents=True, exist_ok=True)

    fresh: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "contract_version": CONTRACT.get("contract_version"),
        "work_id": work_dir.name,
        "work_dir": str(work_dir),
        "mode": mode,
        "source": bind(Path(spec_data["source_deck"])) if spec_data.get("source_deck") else None,
        "edit_contract": {key: spec_data.get(key) for key in ("edit_intent", "review_findings", "preserve", "change_summary_required")},
        "state": "(absent)", "inputs": {},
        "workflow": {
            "state_file": str(workflow_state_path),
            "summary_file": str(Path(str(intake["summary_file"])).resolve()),
            "summary_sha256": str(intake["summary_sha256"]),
        },
        "build": {"build_count": 0, "repair_count": 0, "pending_repair": False},
        "render": {}, "qa": {}, "history": [],
    }
    scope = spec_data.get("research_scope", "C")
    external = any(item.get("source_type") not in {"user-file", "experiment", "interview", "survey"} for item in spec_data.get("evidence_ledger", []))
    pack_on_disk = args.research_pack or work_dir / "research-pack.json"
    if args.research_pack or scope in {"A", "B", "D"} or external or Path(pack_on_disk).is_file():
        spec, pack, validation, evidence_map = compile_research_for_plan(work_dir, spec, args)
        args.research_pack, args.research_validation, args.evidence_map = pack, validation, evidence_map
        spec_data = yaml.safe_load(spec.read_text(encoding="utf-8"))
        if not isinstance(spec_data, dict):
            raise RefusedError("compiled Slide Spec must be an object")
        receipt = execution_receipt(work_dir, "research", pack)
        fresh["research"] = {"required": True, "scope": scope, "agent": receipt["agent"], "spawn_verified": True, "execution": bind(work_dir / "research-execution.json")}
    if manifest and args.force:
        fresh["build"]["repair_count"] = int((manifest.get("build") or {}).get("repair_count") or 0)
        fresh["history"] = list(manifest.get("history") or [])

    ad_report = work_dir / "art-direction-check.json"
    ad_check = _runner([
        sys.executable, str(HERE / "art_direction_check.py"), str(art),
        "--work-dir", str(work_dir),
        "--output", str(ad_report), "--json",
    ])
    if ad_report.is_file():
        fresh["inputs"]["art_direction_check"] = bind(ad_report)
    if ad_check.returncode != 0:
        detail = (ad_check.stderr or ad_check.stdout or "").strip()
        raise RefusedError(
            f"Art Direction blocked plan (exit {ad_check.returncode}): {detail[:400]} "
            f"— fix art-direction.yaml against the checker before plan; report: {ad_report}"
        )

    preflight_report = work_dir / "copy-fit-preflight.json"
    pre = _runner([
        sys.executable, str(HERE / "copy_fit_preflight.py"), "--slide-spec", str(spec),
        "--art-direction", str(art), "--output", str(preflight_report),
    ])
    if preflight_report.is_file():
        fresh["inputs"]["copy_fit_preflight"] = bind(preflight_report)
    if pre.returncode != 0:
        detail = (pre.stderr or pre.stdout or "").strip()
        raise RefusedError(f"copy-fit preflight blocked plan (exit {pre.returncode}): {detail[:400]}")

    lock = work_dir / "slide-spec-lock.json"
    freeze_argv = [
        sys.executable, str(HERE / "slide_spec_guard.py"), "freeze",
        "--slide-spec", str(spec), "--validation-report", str(validation_report),
        "--lock-file", str(lock), "--reason", args.reason,
    ]
    for flag, path in (("--research-pack", args.research_pack), ("--research-validation", args.research_validation), ("--evidence-map", args.evidence_map)):
        if path:
            freeze_argv += [flag, str(path.resolve())]
    frozen = _runner(freeze_argv)
    if frozen.returncode != 0 or not lock.is_file():
        detail = (frozen.stderr or frozen.stdout or "").strip()
        raise RefusedError(f"slide_spec_guard freeze failed (exit {frozen.returncode}): {detail[:400]}")

    fresh["inputs"].update({
        "slide_spec": bind(spec), "spec_lock": bind(lock),
        "slide_spec_report": bind(validation_report), "art_direction": bind(art),
    })
    for key, path in (("visual_generation_report", args.visual_generation_report), ("evidence_map", args.evidence_map), ("research_pack", args.research_pack), ("research_validation", args.research_validation)):
        if path:
            resolved = path.resolve()
            if not resolved.is_file():
                raise RefusedError(f"{key} does not exist: {resolved}")
            fresh["inputs"][key] = bind(resolved)

    fresh["state"] = "planned"
    record(fresh, "plan", "(absent)", "planned")
    if mode == "edit_ooxml":
        unpacked = work_dir / "ooxml"
        if unpacked.exists():
            raise RefusedError("ooxml workspace already exists; use a new work-id for a new plan")
        unpack = _runner([sys.executable, str(PPTX_TOOL), "unpack", fresh["source"]["path"], "--output", str(unpacked)])
        if unpack.returncode != 0 or not unpacked.is_dir():
            raise RefusedError("source unpack failed")
        scaffold_info = {"slides": len(spec_data.get("slides") or []), "pages": []}
    else:
        scaffold_info = _scaffold.scaffold_generator(work_dir, spec)
        if mode == "rebuild_from_source":
            analysis = work_dir / "source-analysis.md"
            if not analysis.is_file() or not analysis.read_text(encoding="utf-8").strip():
                raise RefusedError("rebuild_from_source requires source-analysis.md before plan")
            fresh["inputs"]["source_analysis"] = bind(analysis)
    fresh["scaffold"] = {
        "slides": scaffold_info["slides"],
        "pages": scaffold_info["pages"],
    }
    summary = write_stage_summary(
        work_dir,
        "planned",
        [
            f"- spec: `{spec}`",
            f"- art-direction: `{art}`",
            f"- pages scaffolded: {scaffold_info['slides']} → `pages/`",
            f"- composition dir: `{work_dir / 'composition'}`",
            "- next: fill `pages/pNN-*.js` (parallel Edit), then `ppt_pipeline.py build`",
            "- do not re-read the Slide Spec or Art Direction unless the hash changed",
        ],
    )
    fresh["stage_summary"] = bind(summary)
    save_manifest(work_dir, fresh)
    mirror_workflow_state(fresh, "planned")
    print(f"ppt_pipeline: planned — {manifest_path(work_dir)}")
    print(f"ppt_pipeline: scaffolded {scaffold_info['slides']} page module(s) under {work_dir / 'pages'}")
    return 0


def enforce_page_copy_fidelity(work_dir: Path, spec: Path) -> None:
    """Refuse a build whose page modules paraphrase the Slide Spec copy.

    `pptx_actual_content_check.py` can only run after the deck is built and
    rendered, so a paraphrased page is normally discovered at QA -- after build,
    render and the first QA stage have been paid for. Comparing the page modules
    against the Spec first turns that cascade into a single Edit.
    """
    pages_dir = work_dir / "pages"
    if not pages_dir.is_dir():
        return
    report = work_dir / "page-copy-fidelity.json"
    proc = _runner([
        sys.executable, str(HERE / "page_copy_fidelity_check.py"),
        "--slide-spec", str(spec), "--pages-dir", str(pages_dir), "--output", str(report),
    ])
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RefusedError(
            f"page copy fidelity blocked build; restore the planned copy verbatim: {detail[:600]}"
        )


def cmd_build(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, BUILD_FROM, "build")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    state = str(manifest.get("state"))
    build_info = manifest.setdefault("build", {})
    pre_qa_fix = pre_qa_failed_current(manifest)
    if state == "producing" and not build_info.get("pending_repair") and not pre_qa_fix:
        raise RefusedError("repeat build refused; run repair after QA before rebuilding")

    inputs = manifest.get("inputs") or {}
    lock = Path(str((inputs.get("spec_lock") or {}).get("path") or ""))
    spec = Path(str((inputs.get("slide_spec") or {}).get("path") or ""))
    if not lock.is_file():
        raise RefusedError(f"spec lock missing: {lock}")
    check = _runner([
        sys.executable, str(HERE / "slide_spec_guard.py"), "check",
        "--lock-file", str(lock), "--slide-spec", str(spec),
    ])
    if check.returncode != 0:
        detail = (check.stderr or check.stdout or "").strip()
        raise RefusedError(f"spec lock check failed; re-plan first: {detail[:400]}")

    editing = manifest.get("mode") == "edit_ooxml"
    entry = work_dir / "ooxml" if editing else (args.entry or work_dir / "deck.js").resolve()
    if editing:
        bindings = [bind(path) for path in sorted(entry.rglob("*")) if path.is_file()]
        if not bindings:
            raise RefusedError("OOXML workspace is empty")
        fingerprint = stable_hash(bindings)
    else:
        if not entry.is_file():
            raise RefusedError(f"generator entry does not exist: {entry}")
        try:
            _scaffold.assert_page_split(entry, spec)
        except ValueError as exc:
            raise RefusedError(str(exc)) from exc
        enforce_page_copy_fidelity(work_dir, spec)
        fingerprint, bindings = generator_fingerprint(entry)
    previous = str(build_info.get("generator_fingerprint") or "")
    if state == "producing" and (build_info.get("pending_repair") or pre_qa_fix) and previous == fingerprint:
        raise RefusedError(
            "rebuild refused: the generator did not change since the build that failed "
            "(repair or pre-QA fix must edit the reported pages)"
        )

    pptx = work_dir / args.output_name
    if pptx.resolve().parent != work_dir or (manifest.get("source") and pptx.resolve() == Path(manifest["source"]["path"])):
        raise RefusedError("output must be a new file directly inside work-dir")
    if pptx.suffix.lower() != ".pptx":
        raise RefusedError("--output-name must end in .pptx")
    node = os.environ.get("NODE") or "node"
    built = _runner(
        [sys.executable, str(PPTX_TOOL), "pack", str(entry), "--output", str(pptx)] if editing
        else [node, str(BUILDER), "--output", str(pptx), str(entry), *args.generator_args]
    )
    if built.returncode != 0 or not pptx.is_file():
        detail = (built.stderr or built.stdout or "").strip()
        raise RefusedError(f"build failed (exit {built.returncode}): {detail[:600]}")

    build_info.update({
        "entry": str(entry), "pptx": bind(pptx), "generator_files": bindings,
        "generator_fingerprint": fingerprint,
        "build_count": int(build_info.get("build_count") or 0) + 1,
        "pending_repair": False,
    })
    stale_moved = archive_stale_render(work_dir, manifest)
    if stale_moved:
        build_info["stale_evidence"] = stale_moved
    manifest["render"] = {}
    manifest["qa"] = {}
    pre_qa = run_pre_qa_gates(manifest, work_dir)
    manifest["pre_qa"] = pre_qa
    before = str(manifest.get("state"))
    manifest["state"] = "producing"
    record(
        manifest, "build", before, "producing",
        generator_fingerprint=fingerprint, stale_render_moved=len(stale_moved),
        pre_qa_ok=pre_qa["ok"], pre_qa_blockers=pre_qa["blockers"],
    )
    save_manifest(work_dir, manifest)
    summary_lines = [
        f"- pptx: `{pptx}` sha256 {build_info['pptx']['sha256'][:12]}",
        f"- builds: {build_info['build_count']} repairs: {build_info.get('repair_count', 0)}",
        f"- generator files: {len(build_info.get('generator_files') or [])}",
        f"- previous render evidence archived: {len(stale_moved)}",
    ]
    if pre_qa["ok"]:
        summary_lines.append(
            "- pre-QA (deterministic gates): green — next: `ppt_pipeline.py render`, "
            "then Read contact-sheet + blocker PNGs (CD-9)"
        )
    else:
        summary_lines.append(
            f"- pre-QA (deterministic gates): BLOCKED with {pre_qa['blockers']} blockers "
            f"(round {pre_qa['rounds']}/{pre_qa['max_rounds']}) — run `next --json`; the fix "
            "path (builder edits the reported pages, rebuild) consumes no repair round"
        )
    write_stage_summary(work_dir, "producing", summary_lines)
    mirror_workflow_state(manifest, "producing")
    print(f"ppt_pipeline: built {pptx.name} (builds {build_info['build_count']}, repairs {build_info.get('repair_count', 0)})")
    if pre_qa["ok"]:
        print("ppt_pipeline: deterministic pre-QA green (rendered + actual-content) — render next")
    else:
        print(
            f"ppt_pipeline: deterministic pre-QA FAILED: {pre_qa['blockers']} blockers BEFORE any "
            f"render/critic cost (round {pre_qa['rounds']}/{pre_qa['max_rounds']}) — run "
            "`next --json` for the fix path; do NOT render or spawn the critic on this build"
        )
        for item in pre_qa["problems"][:5]:
            print(f"  [{item['severity']}] {item['gate']}/{item['code']} — {str(item['message'])[:160]}")
    return 0


def make_contact_sheet(
    pages: list[Path], output: Path, cols: int = 3,
    thumb_output: Path | None = None, thumb_width: int = 1024,
) -> None:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RefusedError("Pillow is required for contact-sheet generation") from exc
    if not pages:
        raise RefusedError("render produced no pages")
    opened = [Image.open(path).convert("RGB") for path in pages]
    width = min(480, max(image.width for image in opened))
    thumbs = []
    for image in opened:
        ratio = width / image.width
        thumb = image.resize((width, max(1, int(image.height * ratio))))
        thumbs.append(thumb)
    cell_h = max(image.height for image in thumbs)
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (width * cols, cell_h * rows), "white")
    for index, image in enumerate(thumbs):
        framed = ImageOps.expand(image, border=2, fill="black")
        x = (index % cols) * width
        y = (index // cols) * cell_h
        sheet.paste(framed, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    if thumb_output is not None:
        # 主会话用的廉价概览：2026-09-16 实测全尺寸 contact-sheet.png 有 844KB，
        # 12 页逐页 PNG 更是每张 200-500KB。缩略图 ~100KB，token 当量差一个量级。
        ratio = min(1.0, thumb_width / sheet.width)
        small = sheet.resize((max(1, int(sheet.width * ratio)), max(1, int(sheet.height * ratio))))
        small.save(thumb_output, "JPEG", quality=72)
    for image in opened:
        image.close()


def make_contact_thumb(pages: list[Path], output: Path, thumb_width: int = 1024) -> None:
    """Regenerate only the cheap overview thumb (render cache-hit path)."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise RefusedError("Pillow is required for contact-sheet generation") from exc
    if not pages:
        return
    opened = [Image.open(path).convert("RGB") for path in pages]
    width = min(480, max(image.width for image in opened))
    thumbs = []
    for image in opened:
        ratio = width / image.width
        thumbs.append(image.resize((width, max(1, int(image.height * ratio)))))
    cols = 3
    cell_h = max(image.height for image in thumbs)
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (width * cols, cell_h * rows), "white")
    for index, image in enumerate(thumbs):
        sheet.paste(image, ((index % cols) * width, (index // cols) * cell_h))
    ratio = min(1.0, thumb_width / sheet.width)
    small = sheet.resize((max(1, int(sheet.width * ratio)), max(1, int(sheet.height * ratio))))
    output.parent.mkdir(parents=True, exist_ok=True)
    small.save(output, "JPEG", quality=72)
    for image in opened:
        image.close()


def cmd_render(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, {"producing", "qa"}, "render")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    if pre_qa_failed_current(manifest):
        raise RefusedError(
            "pre-QA gates failed for this build — fix the reported pages and rebuild before "
            "rendering (run `next --json`: that path consumes no repair round)"
        )
    pptx = pptx_path(manifest)
    if not pptx.is_file():
        raise RefusedError("no built PPTX in manifest")
    pptx_sha = sha256_file(pptx)
    if render_is_current(manifest):
        render = manifest.get("render") or {}
        old_contact = Path(str((render.get("contact_sheet") or {}).get("path") or ""))
        old_thumb = Path(str((render.get("contact_sheet_thumb") or {}).get("path") or ""))
        if old_thumb and not old_thumb.is_file():
            # 旧 manifest 没有缩略图字段或文件丢失：从已绑定的页图补生成。
            page_paths = [Path(str(item.get("path"))) for item in render.get("pages") or []]
            existing = [path for path in page_paths if path.is_file()]
            if existing:
                make_contact_thumb(existing, old_thumb or work_dir / "contact-sheet-thumb.jpg")
        record(
            manifest, "render", str(manifest.get("state")), str(manifest.get("state")),
            page_count=int(render.get("page_count") or 0), reused=True,
        )
        save_manifest(work_dir, manifest)
        print(f"ppt_pipeline: render reused — {old_contact}")
        return 0

    render_dir = work_dir / "render"
    if args.cols < 1 or not args.prefix or Path(args.prefix).name != args.prefix or any(ch in args.prefix for ch in "/\\"):
        raise RefusedError("render requires positive cols and a plain filename prefix")
    if not render_dir.resolve().is_relative_to(work_dir):
        raise RefusedError("render directory must stay inside work-dir")
    proc = _runner([
        sys.executable, str(PPTX_TOOL), "render", str(pptx),
        "--output-dir", str(render_dir), "--prefix", args.prefix,
    ])
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RefusedError(f"render failed (exit {proc.returncode}): {detail[:500]}")
    payload = None
    with contextlib.suppress(json.JSONDecodeError):
        payload = json.loads(proc.stdout)
    page_values = payload.get("pages") if isinstance(payload, dict) else None
    pages = [Path(str(path)) for path in page_values] if isinstance(page_values, list) else sorted(render_dir.glob(f"{args.prefix}*.png"))
    if not pages or not all(path.is_file() for path in pages):
        raise RefusedError("render reported success but page images are missing")
    contact = work_dir / "contact-sheet.png"
    thumb = work_dir / "contact-sheet-thumb.jpg"
    make_contact_sheet(pages, contact, args.cols, thumb_output=thumb)
    manifest["render"] = {
        "pptx_sha256": pptx_sha,
        "pages": [bind(path) for path in pages],
        "contact_sheet": bind(contact),
        "contact_sheet_thumb": bind(thumb),
        "page_count": len(pages),
        "rendered_at": now(),
    }
    record(manifest, "render", str(manifest.get("state")), str(manifest.get("state")), page_count=len(pages))
    save_manifest(work_dir, manifest)
    print(f"ppt_pipeline: rendered {len(pages)} pages — contact sheet: {contact}")
    print(f"ppt_pipeline: cheap overview thumb: {thumb}")
    return 0


def cmd_qa(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, QA_FROM, "qa")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    pptx = pptx_path(manifest)
    if not pptx.is_file():
        raise RefusedError("no built PPTX in manifest")
    visual_review = args.visual_review.resolve() if args.visual_review else None
    vgr = work_dir / "visual-generation-report.json"
    if not (manifest.get("inputs") or {}).get("visual_generation_report") and vgr.is_file():
        manifest.setdefault("inputs", {})["visual_generation_report"] = bind(vgr)
    notes = args.notes.resolve() if args.notes else None
    previews = [Path(p).resolve() for p in (args.preview or [])]
    if not render_is_current(manifest):
        raise RefusedError("QA requires current, hash-verified render evidence; run render")
    if notes is None and (work_dir / "speaker-notes.md").is_file():
        notes = work_dir / "speaker-notes.md"
    if not previews:
        # Contact sheet is supplemental evidence, not an extra slide: delivery
        # requires exactly one preview per slide.
        previews = [Path(item["path"]) for item in manifest["render"]["pages"]]
    review = load_json(visual_review) if visual_review else None
    expected_pages = {str(i): item["sha256"] for i, item in enumerate(manifest["render"]["pages"], 1)}
    if not review or review.get("pptx_sha256") != sha256_file(pptx) or review.get("contact_sheet_sha256") != manifest["render"]["contact_sheet"]["sha256"] or review.get("page_sha256") != expected_pages:
        raise RefusedError("visual review must bind the current PPTX, contact sheet and every page SHA256")
    receipt = execution_receipt(work_dir, "critic", visual_review)
    for item in [manifest["render"]["contact_sheet"], *manifest["render"]["pages"]]:
        if receipt.get("reads", {}).get(item["path"]) != item["sha256"]:
            raise RefusedError("independent critic did not read every current render image")
    fingerprint = qa_input_fingerprint(pptx, visual_review, notes, previews)
    fingerprint = stable_hash([fingerprint, manifest.get("inputs"), bind(work_dir / "critic-execution.json"), args.allow_missing_preview])
    old_qa = manifest.get("qa") or {}
    old_report = Path(str((old_qa.get("report") or {}).get("path") or ""))
    cached_bindings = [old_qa.get("report") or {}, *(old_qa.get("stages") or {}).values()]
    if manifest.get("state") == "qa" and old_qa.get("input_fingerprint") == fingerprint and old_report.is_file() and all(binding_is_current(item) for item in cached_bindings):
        ok = bool(old_qa.get("ok"))
        record(manifest, "qa", "qa", "qa", reused=True, blockers=int(old_qa.get("blockers") or 0))
        save_manifest(work_dir, manifest)
        print(f"ppt_pipeline: QA reused — {'ok' if ok else 'blocked'} | {old_report}")
        return 0 if ok else 2

    stages = build_qa_stages(
        manifest, work_dir, visual_review=visual_review, notes=notes,
        previews=previews, allow_missing_preview=args.allow_missing_preview,
    )
    if not stages:
        raise RefusedError("QA DAG is empty")
    problems: list[dict[str, Any]] = []
    reports: dict[str, Any] = {}
    for stage in stages:
        ok, stage_problems, binding = collect(stage)
        reports[stage.artifact] = binding
        if not ok and stage.name in QA_DERIVED_AFTER_UPSTREAM_FAILURE and any(
            not data.get("ok", True) for name, data in reports.items() if name != stage.artifact
        ):
            for item in stage_problems:
                item["derived"] = True
            binding["derived_from_upstream"] = True
        problems.extend(stage_problems)
        if not ok and stage.name in QA_HARD_STOP_STAGES:
            break
    regressions, gate_history = gate_regressions(work_dir, reports)
    problems.extend(regressions)
    problems = dedupe(problems)
    if set(reports) != set(QA_ORDER):
        problems.append({"gate": "pipeline", "severity": "major", "code": "missing_stages", "message": "All QA stages, including delivery, must run and pass"})
    counts = {s: sum(1 for p in problems if p["severity"] == s and not p.get("derived")) for s in ("critical", "major", "minor")}
    blockers = counts["critical"] + counts["major"]
    blockers_by_gate: dict[str, list[str]] = {}
    # keys follow qa_order (actual_content), not the display name (actual-content), so the
    # report and `failed_stages` can be read with one vocabulary.
    artifact_of = {stage.name: stage.artifact for stage in stages}
    for item in problems:
        if item.get("derived") or item["severity"] not in QA_BLOCKING_SEVERITIES:
            continue
        gate = str(item.get("gate") or "pipeline")
        blockers_by_gate.setdefault(artifact_of.get(gate, gate), []).append(str(item.get("code") or "issue"))
    failed_stages = [name for name, data in reports.items() if not data.get("ok", True)]
    # Round-over-round blocker counts: this is what tells a repair round from a round that
    # only moved blockers around. `next` reports the trend so "keep going or stop" is a
    # reading, not another question to the user.
    rounds = [item for item in (gate_history.get("_rounds") or []) if isinstance(item, dict)]
    rounds.append({"round": len(rounds) + 1, "blockers": blockers, "failed": failed_stages})
    gate_history["_rounds"] = rounds[-8:]
    qa_report = {
        "ok": blockers == 0, "pipeline_version": MANIFEST_VERSION,
        "qa_order": list(QA_ORDER), "pptx": str(pptx),
        "counts": {"blockers": blockers, **counts}, "problems": problems, "reports": reports,
        # Every content gate runs before this report is written, so a repair round can be
        # handed the complete blocker set in one go instead of discovering one gate per round.
        "failed_stages": failed_stages, "blockers_by_gate": blockers_by_gate,
        "derived_problems": [item["code"] for item in problems if item.get("derived")],
        "gate_regressions": [item["message"] for item in regressions],
    }
    qa_report_path = work_dir / "pipeline-qa.json"
    qa_report_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (work_dir / GATE_HISTORY_NAME).write_text(
        json.dumps(gate_history, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    before = str(manifest.get("state"))
    manifest["qa"] = {
        "ok": qa_report["ok"], "blockers": blockers, "input_fingerprint": fingerprint,
        "report": bind(qa_report_path), "stages": reports,
        "visual_review": bind(visual_review) if visual_review and visual_review.is_file() else None,
        "previews": [bind(path) for path in previews if path.is_file()] or None,
        "notes": bind(notes) if notes and notes.is_file() else None,
        "critic_execution": bind(work_dir / "critic-execution.json"),
        "stage_cost_ms": {name: data["duration_ms"] for name, data in reports.items() if "duration_ms" in data},
    }
    manifest["state"] = "qa"
    record(manifest, "qa", before, "qa", input_fingerprint=fingerprint)
    save_manifest(work_dir, manifest)
    mirror_workflow_state(manifest, "qa")
    names = ", ".join(name for name, data in reports.items() if data.get("checked")) or "none"
    line = (
        f"ppt_pipeline: {'ok' if qa_report['ok'] else 'blocked'} — blockers {blockers} "
        f"(critical {counts['critical']}, major {counts['major']}), minor {counts['minor']} | "
        f"stages: {names} | failed: {', '.join(failed_stages) or 'none'} | report: {qa_report_path}"
    )
    summary_lines = [f"- {line}", f"- report: `{qa_report_path}`"]
    if blockers_by_gate:
        summary_lines.append(
            "- blockers by gate: "
            + "; ".join(f"{gate}: {', '.join(codes)}" for gate, codes in sorted(blockers_by_gate.items()))
        )
        summary_lines.append(
            "- every content gate already ran on this build — hand the whole list to ONE repair "
            "round; do not fix one gate per round (that cost 6 rounds and ~199M tokens on 2026-09-17)"
        )
    summary_lines.append("- next: `ppt_pipeline.py complete` if ok, else `repair --reason …` then rebuild")
    write_stage_summary(work_dir, "qa", summary_lines)
    print(line)
    for item in problems[: args.max_items]:
        mark = " (derived)" if item.get("derived") else ""
        print(f"  [{item['severity']}]{mark} {item['gate']}/{item['code']} — {str(item['message'])[:200]}")
    return 0 if qa_report["ok"] else 2


def repair_budget(manifest: dict[str, Any] | None) -> dict[str, Any]:
    """Base budget + rounds granted this run, read from the manifest.

    The budget used to be a bare constant, so a run that ran out of rounds had nowhere to
    record a decision except the installed plugin's contract file. Grants live in the
    manifest instead: they survive the plugin being reinstalled, they travel with the work
    id, and they are auditable next to the QA rounds that justified them.
    """
    grants = []
    for entry in ((manifest or {}).get("build") or {}).get("repair_budget_grants") or []:
        if isinstance(entry, dict):
            grants.append(entry)
    granted = sum(int(entry.get("rounds") or 0) for entry in grants)
    return {
        "base": MAX_REPAIRS,
        "granted": granted,
        "effective": MAX_REPAIRS + granted,
        "hard_cap": MAX_REPAIRS_HARD_CAP,
        "grants": grants,
    }


def cmd_repair(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, {"qa"}, "repair")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    blockers = int((manifest.get("qa") or {}).get("blockers") or 0)
    if blockers == 0 and not args.force:
        raise RefusedError("QA has no blockers; complete instead of repairing")
    build_info = manifest.setdefault("build", {})
    repairs = int(build_info.get("repair_count") or 0)
    if args.extend:
        # 提额必须写明"这轮要修什么、上轮 blocker 差异是什么"：契约要求的不是更大的预算，
        # 而是不同的做法。trend 一并记录，让"flat/worse 还继续加轮次"在报告里留下痕迹。
        reason = str(args.extend_reason or "").strip()
        if len(reason) < 24:
            raise RefusedError(
                "repair --extend needs --extend-reason describing the round-over-round blocker "
                "diff (what was resolved, what is new). Repeating the same approach with a bigger "
                "budget is not a repair strategy — `next --json` carries repair_convergence."
            )
        budget = repair_budget(manifest)
        if budget["effective"] + int(args.extend) > MAX_REPAIRS_HARD_CAP:
            raise RefusedError(
                f"repair budget hard cap reached: base {MAX_REPAIRS} + granted {budget['granted']} "
                f"+ requested {int(args.extend)} exceeds {MAX_REPAIRS_HARD_CAP} "
                f"(contract max_repairs_hard_cap). Deliver what is on disk as `incomplete` instead."
            )
        convergence = repair_convergence(work_dir) or {}
        build_info.setdefault("repair_budget_grants", []).append(
            {
                "rounds": int(args.extend),
                "reason": reason,
                "trend": convergence.get("trend"),
                "blockers_at_grant": blockers,
                "repairs_used": repairs,
            }
        )
        print(
            f"ppt_pipeline: repair budget extended by {int(args.extend)} "
            f"(base {MAX_REPAIRS} + granted {budget['granted'] + int(args.extend)}, "
            f"hard cap {MAX_REPAIRS_HARD_CAP}; trend {convergence.get('trend') or 'unknown'})"
        )
    budget = repair_budget(manifest)
    if repairs >= budget["effective"]:
        raise RefusedError(
            f"repair budget exhausted ({repairs}/{budget['effective']}); mark the task incomplete"
        )
    build_info["repair_count"] = repairs + 1
    build_info["pending_repair"] = True
    build_info.setdefault("repair_reasons", []).append(args.reason)
    before = str(manifest.get("state"))
    manifest["state"] = "producing"
    record(manifest, "repair", before, "producing", repair_count=repairs + 1, reason=args.reason)
    save_manifest(work_dir, manifest)
    mirror_workflow_state(manifest, "producing", reason=args.reason)
    print(f"ppt_pipeline: repair {repairs + 1}/{budget['effective']} — change generator, then build → render → qa")
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    manifest = load_manifest(work_dir)
    require_state(manifest, {"qa"}, "complete")
    assert manifest is not None
    validate_manifest_authorization(manifest)
    qa = manifest.get("qa") or {}
    delivery = (qa.get("stages") or {}).get("delivery") or {}
    if not qa.get("ok"):
        raise RefusedError(f"QA still has {qa.get('blockers', '?')} blocker(s)")
    if not delivery.get("checked") or not delivery.get("ok"):
        raise RefusedError("delivery stage did not pass")
    evidence = [qa.get("report"), qa.get("visual_review"), qa.get("notes"), qa.get("critic_execution"), *(qa.get("previews") or []), *(qa.get("stages") or {}).values()]
    if not render_is_current(manifest) or any(not item or not binding_is_current(item) for item in evidence):
        raise RefusedError("QA evidence changed or disappeared after QA; run QA again")
    if manifest.get("mode") != "create":
        change_summary = work_dir / "change-summary.md"
        if not change_summary.is_file() or not change_summary.read_text(encoding="utf-8").strip():
            raise RefusedError("source-based delivery requires change-summary.md")
    before = str(manifest.get("state"))
    manifest["state"] = "complete"
    record(manifest, "complete", before, "complete")
    save_manifest(work_dir, manifest)
    write_stage_summary(
        work_dir,
        "complete",
        [
            "- QA green; delivery stage ran and was hash-bound.",
            f"- pptx: `{((manifest.get('build') or {}).get('pptx') or {}).get('path')}`",
            "- do not re-inject /sp-deck; run sp-review only if the user asks",
        ],
    )
    mirror_workflow_state(manifest, "complete")
    print("ppt_pipeline: complete — delivery and intake authorization are hash-bound")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.work_dir.resolve())
    if not manifest:
        print(f"ppt_pipeline: no manifest at {manifest_path(args.work_dir.resolve())}")
        return 2
    build = manifest.get("build") or {}
    qa = manifest.get("qa") or {}
    render = manifest.get("render") or {}
    pre_qa = manifest.get("pre_qa") or {}
    budget = repair_budget(manifest)
    granted = f" (base {budget['base']} + granted {budget['granted']})" if budget["granted"] else ""
    pre_qa_state = (
        "green" if pre_qa.get("ok") else
        f"{pre_qa.get('blockers', '-')} blockers (round {pre_qa.get('rounds', '-')}/{pre_qa.get('max_rounds', '-')})"
        if pre_qa else "-"
    )
    print(
        f"ppt_pipeline: {manifest.get('state')} — builds {build.get('build_count', 0)}, "
        f"repairs {build.get('repair_count', 0)}/{budget['effective']}{granted}, "
        f"pre-qa {pre_qa_state}, rendered {render.get('page_count', 0)} | "
        f"qa {'ok' if qa.get('ok') else str(qa.get('blockers', '-')) + ' blockers'}"
    )
    return 0


def gate_regressions(
    work_dir: Path,
    reports: dict[str, Any],
    *,
    blockers: int = 0,
    failed: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """A gate that passed on the previous build and fails now means the change broke it.

    2026-09-17 live: repair round 6 broke `actual_content`, which had passed since build 3.
    Nothing compared gate status across rounds, so the breakage surfaced only as another
    blocker pile, the budget was already spent, and the round had effectively undone its own
    predecessor. Naming the regression at the moment it appears is what makes "repair"
    converge instead of oscillate.

    Returns the problems to add plus the history to persist (round counter per gate).
    """
    path = work_dir / GATE_HISTORY_NAME
    previous: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = loaded
        except (OSError, json.JSONDecodeError):
            previous = {}

    problems: list[dict[str, Any]] = []
    history: dict[str, Any] = {}
    for name, data in reports.items():
        ok = bool(data.get("ok"))
        entry = previous.get(name) if isinstance(previous.get(name), dict) else {}
        history[name] = {"ok": ok, "round": int(entry.get("round") or 0) + 1}
        if entry.get("ok") is True and not ok:
            problems.append(
                {
                    "gate": "pipeline",
                    "severity": "major",
                    "code": "gate_regression",
                    "message": (
                        f"`{name}` passed on the previous build and fails now: the last change "
                        "broke a gate that was already working. Restore it before anything else."
                    ),
                }
            )
    # Gates that did not run this round keep their last state: otherwise a hard stop would
    # silently erase the record of a gate that had been passing.
    for name, entry in previous.items():
        if name.startswith("_"):
            continue
        history.setdefault(name, entry)
    rounds = [item for item in (previous.get("_rounds") or []) if isinstance(item, dict)]
    rounds.append({"round": len(rounds) + 1, "blockers": int(blockers), "failed": list(failed or [])})
    history["_rounds"] = rounds[-8:]
    return problems, history


def repair_convergence(work_dir: Path) -> dict[str, Any] | None:
    """Whether the repair rounds are converging, read from the QA round history.

    2026-09-17 live: the budget was a fixed count of rounds while the blocker count barely
    moved, so the run ended in a user prompt — "repair budget exhausted, 23 majors left, what
    now?" — and the granted rounds included one that only undid its predecessor. Publishing
    the trend lets the main session decide from numbers instead of asking the user to guess,
    and gives it an explicit stop condition when a round made things worse.
    """
    path = work_dir / GATE_HISTORY_NAME
    if not path.is_file():
        return None
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(history, dict):
        return None
    rounds = [item for item in (history.get("_rounds") or []) if isinstance(item, dict)]
    if len(rounds) < 2:
        return None
    previous = int(rounds[-2].get("blockers") or 0)
    current = int(rounds[-1].get("blockers") or 0)
    if current < previous:
        trend = "improving"
        advice = "the blocker count is coming down; another round is justified"
    elif current == previous:
        trend = "flat"
        advice = (
            "the last round removed no blockers net: change the approach or deliver incomplete — "
            "repeating it with more budget is not a repair strategy"
        )
    else:
        trend = "worse"
        advice = (
            "the last round ADDED blockers: recover the regression first; granting more rounds "
            "on the same approach only moves the cost"
        )
    return {
        "rounds": rounds,
        "previous_blockers": previous,
        "current_blockers": current,
        "trend": trend,
        "advice": advice,
    }


def _research_budget(work_dir: Path) -> dict[str, Any] | None:
    """Remaining query quota for an existing pack (gap-fill authorization aid).

    2026-09-17: a gap-fill authorization said "about 6 more" without checking the
    remaining deep-band headroom (7); the researcher ran 8 and the pack hit
    16/15, forcing a full round revert. `next` now reports the exact numbers.
    """
    pack_path = work_dir / "research-pack.json"
    if not pack_path.is_file():
        return None
    try:
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(pack, dict):
        return None
    band = str(pack.get("budget") or "")
    used = len(pack.get("queries") or [])
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from validate_research_pack import BUDGET_CAPS  # noqa: PLC0415
    except ImportError:
        return {"band": band, "used": used, "cap": None, "approved_headroom": 0, "remaining": None}
    caps = BUDGET_CAPS.get(band)
    if caps is None:
        return {"band": band, "used": used, "cap": None, "approved_headroom": 0, "remaining": None}
    extension = pack.get("budget_extension")
    headroom = 0
    if isinstance(extension, dict):
        try:
            extra = int(extension.get("extra_queries"))
        except (TypeError, ValueError):
            extra = 0
        if (
            extra >= 1
            and str(extension.get("approved_by") or "") == "user"
            and str(extension.get("reason") or "").strip()
        ):
            headroom = extra
    return {
        "band": band,
        "used": used,
        "cap": caps["queries"],
        "approved_headroom": headroom,
        "remaining": caps["queries"] + headroom - used,
    }


def cmd_next(args: argparse.Namespace) -> int:
    """Tell the model what to read and which command to run. CD-1/CD-3/CD-4/CD-9."""
    work_dir = args.work_dir
    manifest = load_manifest(work_dir)
    python = f'"{sys.executable}"'
    pipeline = HERE / "ppt_pipeline.py"
    if not manifest:
        budget = _research_budget(work_dir)
        payload = {
            "state": "(absent)",
            "read": [],
            "forbidden_to_read": ["${CLAUDE_PLUGIN_ROOT}/references/*.md"],
            "read_images": [],
            "next_command": (
                f'{python} "{pipeline}" plan --work-dir "{work_dir}" '
                "--slide-spec <compiled-spec> --validation-report <report> "
                "--art-direction <art-direction.yaml>"
            ),
            "allowed_writes": ["production-summary.md", "art-direction.yaml", "slide-spec.yaml"],
            "notes": (
                "intake first; do not grep plugin source — this command is the discovery API. "
                "If research-pack.json exists in the work-dir, plan compiles evidence-map.json "
                "itself (do not pass --evidence-map). Spawn presentation-researcher from the "
                "MAIN session without `name`."
            ),
        }
        if budget is not None:
            payload["budget"] = budget
            payload["notes"] += (
                " Gap-fill authorization must state the exact remaining query quota; exceeding"
                " the band cap requires a user-approved budget_extension recorded in the pack."
            )
    else:
        state = str(manifest.get("state") or "(absent)")
        summary = work_dir / f"stage-{state}-summary.md"
        read = [str(summary)] if summary.is_file() else []
        forbidden = ["slide-spec.yaml", "art-direction.yaml", "research-pack.json"]
        payload = {
            "state": state,
            "read": read,
            "forbidden_to_read": forbidden,
            "read_images": [],
            "next_command": "",
            "allowed_writes": ["pages/pNN-*.js"],
            "notes": "different pages must be Edit'ed in the same turn (CD-1, CD-2)",
        }
        convergence = repair_convergence(work_dir)
        if convergence:
            payload["repair_convergence"] = convergence
        if state == "planned":
            if manifest.get("mode") == "edit_ooxml":
                payload["next_command"] = f'{python} "{pipeline}" build --work-dir "{work_dir}"'
                payload["allowed_writes"] = [str(work_dir / "ooxml"), str(work_dir / "change-summary.md")]
                payload["notes"] = "Edit unpacked OOXML preserving the source and preserve contract, then build (pack)."
            else:
                # Resume-safe calibration dispatch (2026-09-17): a live session was
                # cut mid calibration-fix round and `next` answered a raw `build`,
                # teaching the MAIN session to edit page modules directly — the one
                # flow builder_guard forbids. Dispatch on what calibration evidence
                # exists so an interrupted session resumes at the right step.
                calibration_manifest = work_dir / "calibration" / "calibration-manifest.json"
                calibration_rendered = bool(list((work_dir / "calibration" / "render").glob("calibration-*.png")))
                if not calibration_manifest.is_file():
                    payload["agent"] = "student-presentation-suite:presentation-builder"
                    payload["notes"] = (
                        "pick 2-3 high-leverage slides (cover + dense/data page + representative visual page) and "
                        "spawn student-presentation-suite:presentation-builder mode=calibration with the absolute "
                        "work-dir and those slide ids (no `name`). It implements only those pages; the rest stay "
                        "scaffolded so an early full build stays impossible. The MAIN session never edits "
                        "pages/pNN-*.js itself. After BUILDER_DONE run calibration_preview.py."
                    )
                elif not calibration_rendered:
                    slides = load_json(calibration_manifest).get("slides") or []
                    slide_args = " ".join(str(slide) for slide in slides)
                    payload["next_command"] = (
                        f'{python} "{HERE / "calibration_preview.py"}" --work-dir "{work_dir}" '
                        f"--slides {slide_args} --json"
                    )
                    payload["notes"] = (
                        "calibration pages exist but no preview render: run calibration_preview.py, then Read the "
                        "preview PNGs in ONE parallel round and judge them against Art Direction."
                    )
                else:
                    payload["agent"] = "student-presentation-suite:presentation-builder"
                    payload["notes"] = (
                        "calibration preview is on disk. If Major/Critical issues remain: respawn the builder "
                        "mode=calibration for only those pages, then rerun calibration_preview.py. If the visual "
                        "system is accepted: spawn the same builder mode=initial to implement every remaining "
                        "scaffold page (calibrated pages are preserved); run build only after BUILDER_DONE."
                    )
        elif state == "producing":
            if pre_qa_failed_current(manifest):
                # Deterministic misses are fixed BEFORE any render or critic cost:
                # the builder edits the reported pages and the deck is rebuilt —
                # no repair round, no critic pass on a doomed deck.
                pre_qa = manifest.get("pre_qa") or {}
                payload["agent"] = "student-presentation-suite:presentation-builder"
                payload["pre_qa"] = {
                    "ok": False,
                    "blockers": pre_qa.get("blockers"),
                    "rounds": pre_qa.get("rounds"),
                    "max_rounds": pre_qa.get("max_rounds", MAX_PRE_QA_REBUILDS),
                    "reports": [
                        str(work_dir / "pre-qa-actual-content.json"),
                        str(work_dir / "pre-qa-rendered.json"),
                    ],
                }
                payload["notes"] = (
                    "deterministic pre-QA gates failed BEFORE any render/critic cost "
                    f"(round {pre_qa.get('rounds')}/{pre_qa.get('max_rounds', MAX_PRE_QA_REBUILDS)}). "
                    "Spawn student-presentation-suite:presentation-builder WITHOUT a name with "
                    "mode=repair, the absolute work-dir and the report paths above — it reads "
                    "them itself. Fix every reported page in one round, then run build again "
                    "(this path consumes NO repair round while the state stays producing). "
                    "Do not render and do not spawn the critic on this build."
                )
            elif render_is_current(manifest):
                render = manifest.get("render") or {}
                contact = Path(str((render.get("contact_sheet") or {}).get("path") or ""))
                thumb = Path(str((render.get("contact_sheet_thumb") or {}).get("path") or ""))
                overview = thumb if (thumb and thumb.is_file()) else contact
                payload["read_images"] = [str(overview), str(work_dir / "render")]
                payload["next_command"] = (
                    f'{python} "{pipeline}" qa --work-dir "{work_dir}" '
                    f'--visual-review "{work_dir / "visual-review.json"}"'
                )
                payload["notes"] = (
                    "Spawn student-presentation-suite:visual-critic WITHOUT a `name` "
                    "parameter — a named Agent call becomes a teammate whose agent_type is the name, "
                    "so SubagentStop never issues critic-execution.json and QA blocks forever. "
                    "Overview: read the cheap contact-sheet-thumb.jpg, not the full-size contact sheet; "
                    "the isolated critic Reads EVERY full-size page (its context never reaches this session). "
                    "Wait for critic-execution.json before QA."
                )
                payload["agent"] = "student-presentation-suite:visual-critic"
                payload["session_segment"] = (
                    "boundary-recommended: build+render is done and this work-dir carries all state. "
                    "Running review+QA in a NEW session (just /sp-deck then `next --json`) avoids "
                    "re-reading this session's history on every request — the single largest cost lever."
                )
            else:
                payload["next_command"] = (
                    f'{python} "{pipeline}" render --work-dir "{work_dir}"'
                )
                payload["notes"] = (
                    "no render evidence for the current PPTX hash; run render first, then "
                    "Read the new contact-sheet + blocker page PNGs in ONE parallel round (CD-9)"
                )
        elif state == "qa":
            qa = manifest.get("qa") or {}
            if qa.get("ok"):
                payload["next_command"] = f'{python} "{pipeline}" complete --work-dir "{work_dir}"'
            else:
                payload["next_command"] = (
                    f'{python} "{pipeline}" repair --work-dir "{work_dir}" --reason "<summary>"'
                )
                payload["notes"] = "fix every blocker page in one parallel Edit round, then build + qa"
        elif state == "complete":
            payload["next_command"] = "(done)"
            payload["notes"] = "do not re-inject /sp-deck"
        else:
            payload["next_command"] = f'{python} "{pipeline}" status --work-dir "{work_dir}"'

    action = "intake"
    if manifest and str(manifest.get("state") or "") == "planned" and manifest.get("mode") != "edit_ooxml":
        # planned create/rebuild keeps the build stage contract (the calibration
        # flow) even when the next step is an agent spawn with no bash command.
        action = "build"
    elif manifest and str(manifest.get("state") or "") == "producing" and pre_qa_failed_current(manifest):
        # the pre-QA fix path is a build-stage rule set: builder edits, rebuild, no repair
        action = "build"
    else:
        for candidate in ("build", "render", "qa", "repair", "complete"):
            if f" {candidate} " in payload["next_command"]:
                action = candidate
                break
    payload["contract"] = {
        "stage": action, "rules": CONTRACT["stage_contracts"][action],
        "qa_order": list(QA_ORDER), "max_repairs": MAX_REPAIRS,
        "contract_sha256": sha256_file(CONTRACT_PATH),
    }
    # 提额是数据决定的事，不是问用户的事：budget 与 trend 一起给出，主会话据此决定续轮、
    # 换做法还是交付 incomplete。`--extend` 把决定写进 manifest，不需要改插件契约文件。
    payload["repair_budget"] = repair_budget(manifest)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"state: {payload['state']}")
    print("read:")
    for item in payload["read"] or ["(none)"]:
        print(f"  - {item}")
    print("forbidden_to_read:")
    for item in payload["forbidden_to_read"]:
        print(f"  - {item}")
    if payload.get("read_images"):
        print("read_images (same turn, parallel):")
        for item in payload["read_images"]:
            print(f"  - {item}")
    print(f"next_command: {payload['next_command']}")
    print(f"allowed_writes: {', '.join(payload['allowed_writes'])}")
    print(f"notes: {payload['notes']}")
    print("stage_contract: " + json.dumps(payload["contract"], ensure_ascii=False))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="verify intake, preflight and freeze -> planned")
    plan.add_argument("--work-dir", type=Path, required=True)
    plan.add_argument("--production-mode", choices=["create", "edit_ooxml", "rebuild_from_source"])
    plan.add_argument("--workflow-state", type=Path, help="confirmed work-dir/workflow-state.json")
    plan.add_argument("--slide-spec", type=Path, required=True)
    plan.add_argument("--validation-report", type=Path, required=True)
    plan.add_argument("--art-direction", type=Path, required=True)
    plan.add_argument("--visual-generation-report", type=Path)
    plan.add_argument("--research-pack", "--pack", type=Path, dest="research_pack")
    plan.add_argument("--research-validation", type=Path)
    plan.add_argument("--evidence-map", type=Path)
    plan.add_argument(
        "--research-execution",
        type=Path,
        help=argparse.SUPPRESS,
    )
    plan.add_argument("--reason", default="initial approved production plan")
    plan.add_argument("--force", action="store_true")
    plan.set_defaults(func=cmd_plan)

    build = sub.add_parser("build", help="build once; repeated builds require repair + changed generator")
    build.add_argument("--work-dir", type=Path, required=True)
    build.add_argument("--entry", type=Path)
    build.add_argument("--output-name", default="deck.pptx")
    build.add_argument("generator_args", nargs="*")
    build.set_defaults(func=cmd_build)

    render = sub.add_parser("render", help="render all pages once and create a contact sheet")
    render.add_argument("--work-dir", type=Path, required=True)
    render.add_argument("--prefix", default="slide")
    render.add_argument("--cols", type=int, default=3)
    render.set_defaults(func=cmd_render)

    qa = sub.add_parser("qa", help="run QA DAG (content gates all run, then one blocker set); identical inputs reuse prior result")
    qa.add_argument("--work-dir", type=Path, required=True)
    qa.add_argument("--visual-review", type=Path)
    qa.add_argument("--notes", type=Path)
    qa.add_argument("--preview", type=Path, nargs="+", action="extend")
    qa.add_argument("--allow-missing-preview", action="store_true")
    qa.add_argument("--max-items", type=int, default=12)
    qa.set_defaults(func=cmd_qa)

    repair = sub.add_parser("repair", help=f"qa blockers -> producing; base budget {MAX_REPAIRS}")
    repair.add_argument("--work-dir", type=Path, required=True)
    repair.add_argument("--reason", required=True)
    repair.add_argument(
        "--extend",
        type=int,
        default=0,
        help=f"grant N extra rounds beyond the base budget (recorded in the manifest; hard cap {MAX_REPAIRS_HARD_CAP})",
    )
    repair.add_argument(
        "--extend-reason",
        help="required with --extend: the round-over-round blocker diff that justifies more rounds",
    )
    repair.add_argument("--force", action="store_true")
    repair.set_defaults(func=cmd_repair)

    complete = sub.add_parser("complete", help="qa + delivery ok -> complete")
    complete.add_argument("--work-dir", type=Path, required=True)
    complete.set_defaults(func=cmd_complete)

    status = sub.add_parser("status", help="one-line manifest summary")
    status.add_argument("--work-dir", type=Path, required=True)
    status.set_defaults(func=cmd_status)

    nxt = sub.add_parser("next", help="what to read and which command to run next")
    nxt.add_argument("--work-dir", type=Path, required=True)
    nxt.add_argument("--json", action="store_true")
    nxt.set_defaults(func=cmd_next)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_work_dir(args.work_dir)
        return args.func(args)
    except RefusedError as exc:
        # 只说"为什么拒绝"会让 agent 去猜下一步（2026-09-16 实测：evidence-map
        # 环节靠试不同参数摸了约 10 轮）。这里固定把 next 命令也一并给出。
        print(f"ppt_pipeline: REFUSED — {exc}", file=sys.stderr)
        print(
            "ppt_pipeline: next step — "
            f'"{sys.executable}" "{HERE / "ppt_pipeline.py"}" next --work-dir "{args.work_dir}"',
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
