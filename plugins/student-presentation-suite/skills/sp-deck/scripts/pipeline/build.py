from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import generator_scaffold as _scaffold  # noqa: E402
from calibration_review import calibration_review  # noqa: E402

from pipeline import core  # noqa: E402
from pipeline.core import (  # noqa: E402
    BUILD_FROM,
    BUILDER,
    HERE,
    MAX_CARRYOVER_BUILDS,
    PPTX_TOOL,
    RefusedError,
    archive_stale_render,
    bind,
    generator_fingerprint,
    load_manifest,
    mirror_workflow_state,
    pre_qa_failed_current,
    record,
    require_state,
    run_pre_qa_gates,
    save_manifest,
    stable_hash,
    validate_manifest_authorization,
    write_stage_summary,
)
from pipeline.scheduler import (  # noqa: E402
    merge_speaker_note_shards,
)
from shared.quality_tiers import calibration_enabled, tier_policy  # noqa: E402


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
    proc = core._runner([
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
    if pre_qa_fix and int((manifest.get("pre_qa") or {}).get("rounds") or 0) >= core.MAX_PRE_QA_REBUILDS and not build_info.get("pending_repair"):
        raise RefusedError("pre-QA retry budget exhausted; register repair before rebuilding")
    declared_round = bool(build_info.get("pending_repair")) or pre_qa_fix
    if state == "producing" and not declared_round:
        # A rebuild whose generator actually changed is a CARRY-OVER build (the builder edited
        # pages after the round's build), not a repeat build; one is allowed per round so the
        # edits land in the artifact instead of waiting for a whole extra round. The
        # pending_repair path below still needs an explicit repair after QA.
        carried = int(build_info.get("carryover_builds") or 0)
        if carried >= MAX_CARRYOVER_BUILDS:
            raise RefusedError("repeat build refused; run repair after QA before rebuilding")
        build_info["carryover_pending"] = True

    inputs = manifest.get("inputs") or {}
    lock = Path(str((inputs.get("spec_lock") or {}).get("path") or ""))
    spec = Path(str((inputs.get("slide_spec") or {}).get("path") or ""))
    if not lock.is_file():
        raise RefusedError(f"spec lock missing: {lock}")
    check = core._runner([
        sys.executable, str(HERE / "slide_spec_guard.py"), "check",
        "--lock-file", str(lock), "--slide-spec", str(spec),
    ])
    if check.returncode != 0:
        detail = (check.stderr or check.stdout or "").strip()
        raise RefusedError(f"spec lock check failed; re-plan first: {detail[:400]}")

    editing = manifest.get("mode") == "edit_ooxml"
    entry = work_dir / "ooxml" if editing else (args.entry or work_dir / "deck.js").resolve()
    if not editing and state == "planned":
        # Authorise the full production build only on an independently reviewed
        # calibration; the doc-only version of this rule was already in SKILL.md
        # and was not followed in the 2026-09-18 live session. Tier policy decides
        # whether calibration applies and how many fix rounds it may spend before
        # remaining majors are carried as recorded risk. Short standard decks (at
        # or below the page line) skip calibration entirely — dispatch and build
        # must consult the SAME page-count frozen at plan time (manifest.scaffold).
        review = calibration_review(work_dir)
        policy = tier_policy(manifest.get("quality_level"))
        deck_pages = (manifest.get("scaffold") or {}).get("slides")
        calibrates = calibration_enabled(
            manifest.get("quality_level"), int(deck_pages) if deck_pages else None
        )
        rounds = int((manifest.get("calibration") or {}).get("rounds") or 0)
        if (
            (calibrates or review["required"])
            and not review["ok"]
            and rounds < policy["calibration_max_rounds"]
        ):
            raise RefusedError(
                "full build refused: " + (review["reason"] or "calibration is not deterministically green")
                + f". Run `next --json`; the review is written to {review['path']}"
            )
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
    if build_info.pop("carryover_pending", False) and previous and previous == fingerprint:
        raise RefusedError(
            "carry-over build refused: no page module changed since the last build, so there is "
            "nothing the previous build is missing"
        )

    pptx = work_dir / args.output_name
    if pptx.resolve().parent != work_dir or (manifest.get("source") and pptx.resolve() == Path(manifest["source"]["path"])):
        raise RefusedError("output must be a new file directly inside work-dir")
    if pptx.suffix.lower() != ".pptx":
        raise RefusedError("--output-name must end in .pptx")
    node = os.environ.get("NODE") or "node"
    # Rebuilds target the same deck.pptx name, and the generator refuses to
    # overwrite existing outputs. Build to a side name and atomically replace
    # only on success, so a failed rebuild leaves the previous artifact bound
    # and on disk instead of a half-state.
    staging = pptx.with_name(f"{pptx.stem}.building{pptx.suffix}")
    staging.unlink(missing_ok=True)
    sidecar_suffixes = (".registry-report.json", ".layout-report.json")
    for suffix in sidecar_suffixes:
        Path(str(staging) + suffix).unlink(missing_ok=True)
    built = core._runner(
        [sys.executable, str(PPTX_TOOL), "pack", str(entry), "--output", str(staging)] if editing
        else [node, str(BUILDER), "--output", str(staging), str(entry), *args.generator_args]
    )
    if built.returncode != 0 or not staging.is_file():
        detail = (built.stderr or built.stdout or "").strip()
        staging.unlink(missing_ok=True)
        for suffix in sidecar_suffixes:
            Path(str(staging) + suffix).unlink(missing_ok=True)
        # The generator's traceback names the failing page module AFTER the
        # RangeError text, which detail[:600] alone usually cuts off — put the
        # page frame first so a fit/Reference refusal is fixable without a
        # re-run just to find the file.
        page_frame = re.search(r"pages[\\/](p[\w.-]+\.js:\d+)", detail)
        location = f"failing page module pages/{page_frame.group(1)} — " if page_frame else ""
        raise RefusedError(
            f"build failed (exit {built.returncode}): {location}{detail[:600]}"
        )
    # Windows 杀毒/索引器会在文件刚关闭后短暂持有锁：与 cjk_fonts._write_package
    # 相同的重试策略，别让一次瞬时 WinError 5 毁掉整次构建。
    for attempt in range(6):
        try:
            os.replace(staging, pptx)
            break
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.3)

    for suffix in sidecar_suffixes:
        source_report = Path(str(staging) + suffix)
        final_report = Path(str(pptx) + suffix)
        if source_report.is_file():
            if suffix == ".registry-report.json":
                report = json.loads(source_report.read_text(encoding="utf-8"))
                report.update(pptx=str(pptx), pptx_sha256=core.sha256_file(pptx))
                source_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(source_report, final_report)
        else:
            final_report.unlink(missing_ok=True)

    # Parallel builders each own a slice of the deck, so none of them can write the single
    # readable notes file without dropping the others' text. Assemble it here instead.
    note_fragments = merge_speaker_note_shards(work_dir)

    declared_round_now = bool(build_info.get("pending_repair")) or pre_qa_fix
    carried_fingerprint = str(build_info.get("generator_fingerprint") or "")
    build_info.update({
        "entry": str(entry), "pptx": bind(pptx), "generator_files": bindings,
        "generator_fingerprint": fingerprint,
        # advance replays builds deterministically (Batch 3.1) and needs the original
        # invocation, not just its outcome.
        "generator_args": list(args.generator_args),
        "build_count": int(build_info.get("build_count") or 0) + 1,
        "pending_repair": False,
        # Counting carry-over builds separately keeps "how many rounds did we spend" honest
        # while letting the leftover edits reach the artifact.
        "carryover_builds": (
            0 if declared_round_now
            else int(build_info.get("carryover_builds") or 0) + (1 if carried_fingerprint else 0)
        ),
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
    if note_fragments:
        summary_lines.append(
            f"- speaker notes assembled from {len(note_fragments)} shard fragment(s) into speaker-notes.md"
        )
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


