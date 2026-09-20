from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import builder_packet as _packet  # noqa: E402
from calibration_review import (  # noqa: E402
    CALIBRATION_DIR_NAME,
    CALIBRATION_MANIFEST_NAME,
    calibration_review,
)  # noqa: E402

from pipeline.convergence import (  # noqa: E402
    repair_budget,
    repair_convergence,
)
from pipeline.core import (  # noqa: E402
    CONTRACT,
    CONTRACT_PATH,
    HERE,
    MAX_PRE_QA_REBUILDS,
    MAX_REPAIRS,
    QA_ORDER,
    ROOT,
    generator_changed_since_build,
    load_json,
    load_manifest,
    pre_qa_failed_current,
    render_is_current,
    sha256_file,
    work_id_receipt_policy,
)
from pipeline.plan import (  # noqa: E402
    _research_budget,
)
from pipeline.scheduler import (  # noqa: E402
    builder_instance_reuse,
    builder_shards,
    observe_packet_failure,
    packet_fallbacks,
    remaining_scaffold_slides,
    slides_named_in_reports,
)


def build_next_payload(work_dir: Path) -> dict[str, Any]:
    """Compute the dispatch answer `next --json` prints (Batch 3 refactor).

    Extracted from cmd_next so `advance` can consult the same dispatch without
    duplicating it: agent boundaries are returned as-is, deterministic commands
    are executed by advance's loop."""
    manifest = load_manifest(work_dir)
    python = f'"{sys.executable}"'
    pipeline = HERE / "ppt_pipeline.py"
    if not manifest:
        budget = _research_budget(work_dir)
        validator = str(ROOT / "scripts" / "validate_slide_spec.py")
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
            "spec_authoring": {
                "schema": str(ROOT / "references" / "slide-spec.schema.json"),
                "validator": (
                    f'{python} "{validator}" <work-dir>/slide-spec.yaml '
                    "--output <work-dir>/spec-validation.json"
                ),
                "must": [
                    "run the validator (or read the schema) BEFORE writing slide-spec.yaml — "
                    "authoring by intuition cost 5 extra rounds on 2026-09-19 (integer ids, "
                    "required content/timing_sec/owner, required visual object per slide)",
                    "validate BEFORE plan: plan refuses without the --validation-report file",
                ],
            },
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
        instance_reuse = builder_instance_reuse(work_dir, manifest)
        if instance_reuse:
            payload["builder_instance_reuse"] = instance_reuse
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
                    payload["builder_mode"] = "calibration"
                    payload["notes"] = (
                        "spawn student-presentation-suite:presentation-builder mode=calibration with the absolute "
                        "work-dir and the packet's slide ids (no `name`). It implements only those pages; the rest stay "
                        "scaffolded so an early full build stays impossible. The MAIN session never edits "
                        "pages/pNN-*.js itself. After BUILDER_DONE run calibration_preview.py."
                    )
                    # Builder Packet (v0.15 Batch 2): project the calibration default
                    # set so the builder gets one task input instead of re-reading
                    # spec + art direction + research pack itself.
                    try:
                        active_packets = _packet.active_packet_descriptors(work_dir, "calibration")
                        if active_packets:
                            descriptor = active_packets[0]
                            cal_slides = list(descriptor["slides"])
                            cal_path = Path(descriptor["packet"])
                            packet_source = "active calibration override"
                        else:
                            cal_slides = _packet.default_calibration_slides(work_dir)
                            cal_path = None
                            packet_source = "default calibration set"
                        if cal_slides:
                            if cal_path is None:
                                cal_path, _ = _packet.write_packet(work_dir, "calibration", cal_slides)
                                _packet.record_active_round(
                                    work_dir,
                                    "calibration",
                                    [{"packet": str(cal_path), "slides": list(cal_slides)}],
                                )
                            payload["builder_packet"] = {
                                "mode": "calibration",
                                "slides": cal_slides,
                                "packet": str(cal_path),
                            }
                            payload["notes"] += (
                                f" A packet projecting the {packet_source} ({', '.join(map(str, cal_slides))}) "
                                f"is at {cal_path} — pass it as the builder's task input."
                            )
                            if not active_packets:
                                payload["notes"] += (
                                    " Keep that default unless you can name a visual archetype it misses: it is "
                                    "chosen for distinct grammars, not for page importance, so 'these pages matter "
                                    "more' is not a reason to swap. To override, run builder_packet.py --mode "
                                    "calibration --slides <ids> and read its coverage block — swap only when it "
                                    "covers at least as many distinct archetypes; trading one grammar for another "
                                    "is fine, dropping one is not."
                                )
                            try:
                                coverage = _packet.calibration_coverage(work_dir, cal_slides)
                                if coverage:
                                    payload["calibration_coverage"] = coverage
                            except Exception:
                                pass
                    except Exception as exc:
                        observe_packet_failure(work_dir, payload, "calibration", exc)
                elif not calibration_rendered:
                    slides = load_json(calibration_manifest).get("slides") or []
                    slide_args = " ".join(str(slide) for slide in slides)
                    payload["next_command"] = (
                        f'{python} "{HERE / "calibration_preview.py"}" --work-dir "{work_dir}" '
                        f"--slides {slide_args} --json"
                    )
                    payload["notes"] = (
                        "calibration pages exist but no preview render: run calibration_preview.py, then hand "
                        "the preview to the independent visual-critic (step 8) — do NOT accept the visual "
                        "system on the main session's own reading of the PNGs. `next --json` after the render "
                        "names the exact critic spawn and its review path."
                    )
                else:
                    review = calibration_review(work_dir)
                    if not review["ok"]:
                        payload["calibration"] = {
                            "slides": review["slides"],
                            "pptx": str(work_dir / CALIBRATION_DIR_NAME / "calibration.pptx"),
                            "render": [
                                str(path)
                                for path in sorted((work_dir / CALIBRATION_DIR_NAME / "render").glob("calibration-*.png"))
                            ],
                            "manifest": str(work_dir / CALIBRATION_DIR_NAME / CALIBRATION_MANIFEST_NAME),
                            "review_output": review["path"],
                            "receipt_output": review["receipt"],
                            "critic_preview_map": str(work_dir / "critic-preview-map.json"),
                            "status": review["reason"],
                        }
                        if review.get("action") == "builder":
                            repair_slides = review.get("repair_slides") or review["slides"]
                            payload["agent"] = "student-presentation-suite:presentation-builder"
                            payload["builder_mode"] = "calibration"
                            packets = _packet.prepare_packets(work_dir, "calibration", repair_slides)
                            if packets:
                                payload["builder_packet"] = packets[0]
                            payload["notes"] = (
                                f"The independent calibration review requires a targeted builder repair: "
                                f"{review['reason']}. Spawn presentation-builder (no `name`) with "
                                f"mode=calibration for slides {repair_slides} using the packet above, then "
                                "rerun calibration_preview.py for the complete calibration set."
                            )
                        else:
                            payload["agent"] = "student-presentation-suite:visual-critic"
                            payload["notes"] = (
                                "Calibration evidence needs an independent visual-critic run. Spawn "
                                "student-presentation-suite:visual-critic (no `name`) with the absolute "
                                "work-dir. The runtime hook will create a scope=calibration "
                                "critic-preview-map.json; the critic must read every mapped preview and "
                                "write only its review_output. Scope the review to repeated structure "
                                "across different page roles, Art Direction conformance, and whether roles "
                                "remain visually distinct. The main session's own read is not a review. "
                                f"Current status: {review['reason']}"
                            )
                    else:
                        remaining = remaining_scaffold_slides(work_dir)
                        if not remaining:
                            # Every scaffold page is implemented (no stub markers left): the
                            # initial builders are done, so the next step is the first full
                            # build — a deterministic step `advance` executes itself.
                            payload["next_command"] = f'{python} "{pipeline}" build --work-dir "{work_dir}"'
                            payload["notes"] = (
                                "calibration is independently reviewed and green and every scaffold "
                                "page is implemented: run build (advance executes it), then pre-QA → "
                                "render → critic follow automatically."
                            )
                        else:
                            payload["agent"] = "student-presentation-suite:presentation-builder"
                            payload["builder_mode"] = "initial"
                            payload["notes"] = (
                                "calibration is independently reviewed and green. Spawn the same builder "
                                "mode=initial to implement every remaining scaffold page (calibrated pages are "
                                "preserved); run build only after BUILDER_DONE."
                            )
                            shards = builder_shards(remaining, work_dir)
                            if shards:
                                payload["builder_shards"] = shards
                                payload["notes"] += (
                                    f" {len(remaining)} pages remain: spawn all {shards['parallel']} shards in "
                                    "ONE message (see builder_shards) so the page work runs concurrently — "
                                    "sharding changes no gate, only the wall clock."
                                )
                            # Builder Packet (v0.15 Batch 2): one packet per instance, projected
                            # from the frozen inputs so builders stop re-reading them.
                            try:
                                packets = _packet.prepare_packets(work_dir, "initial", remaining)
                                if packets:
                                    payload["builder_packets"] = packets
                                    payload["notes"] += (
                                        " One packet per instance is generated under builder-packets/ "
                                        "(builder_packets field) — pass each builder its packet path as the "
                                        "task input; the packet projects slides, style, evidence and allowed "
                                        "files, so builders must not re-read the frozen inputs."
                                    )
                            except Exception as exc:
                                observe_packet_failure(work_dir, payload, "initial", exc)
        elif state == "producing":
            pending_repair = bool((manifest.get("build") or {}).get("pending_repair"))
            if (pending_repair or pre_qa_failed_current(manifest)) and generator_changed_since_build(manifest):
                # The repair / pre-QA-fix builder came back and edited pages — the
                # fingerprint moved. The next step is the rebuild that lands those edits,
                # which is deterministic: advance runs it and continues into render → critic
                # in the same call instead of costing the model an extra round-trip.
                payload["next_command"] = f'{python} "{pipeline}" build --work-dir "{work_dir}"'
                payload["notes"] = (
                    "the generator changed since the last build (repair/pre-QA fix edits landed): "
                    "rebuild first so the QA evidence matches the deck about to be reviewed"
                )
            elif pre_qa_failed_current(manifest):
                # Deterministic misses are fixed BEFORE any render or critic cost:
                # the builder edits the reported pages and the deck is rebuilt —
                # no repair round, no critic pass on a doomed deck.
                pre_qa = manifest.get("pre_qa") or {}
                payload["agent"] = "student-presentation-suite:presentation-builder"
                payload["builder_mode"] = "repair"
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
                fixable = slides_named_in_reports(
                    work_dir, ("pre-qa-quality.json", "pre-qa-actual-content.json", "pre-qa-rendered.json")
                )
                shards = builder_shards(fixable, work_dir)
                if shards:
                    payload["builder_shards"] = shards
                # Builder Packet (v0.15 Batch 2): repair packet per instance, blockers
                # projected from the pre-QA reports instead of the builder re-reading them.
                try:
                    pre_qa_reports = [
                        name
                        for name in ("pre-qa-actual-content.json", "pre-qa-rendered.json", "pre-qa-quality.json")
                        if (work_dir / name).is_file()
                    ]
                    packets = _packet.prepare_packets(
                        work_dir, "repair", fixable or None, pre_qa_reports
                    ) if fixable else []
                    if packets:
                        payload["builder_packets"] = packets
                        payload["notes"] += (
                            " Repair packets with the projected blockers are generated under "
                            "builder-packets/ (builder_packets field) — pass each builder its packet "
                            "path; it must not re-read the reports the packet covers."
                        )
                except Exception as exc:
                    observe_packet_failure(work_dir, payload, "repair", exc)
            elif pending_repair:
                # A recorded repair with an UNCHANGED generator means the repair builder
                # has not edited yet. The boundary is the repair builder, not the critic:
                # the render evidence is still technically current, but the deck is about
                # to change, so reviewing the old render would waste a critic pass.
                payload["agent"] = "student-presentation-suite:presentation-builder"
                payload["builder_mode"] = "repair"
                payload["notes"] = "repair is recorded; fix the blocker pages, then build → render → qa"
                try:
                    blocker_slides = slides_named_in_reports(
                        work_dir,
                        ("pipeline-qa.json", "pre-qa-quality.json", "pre-qa-actual-content.json", "pre-qa-rendered.json"),
                    )
                    if blocker_slides and (work_dir / "pipeline-qa.json").is_file():
                        packets = _packet.prepare_packets(work_dir, "repair", blocker_slides, ["pipeline-qa.json"])
                        if packets:
                            payload["builder_packets"] = packets
                            payload["notes"] += (
                                " Repair packets with the projected blockers are generated under "
                                "builder-packets/ (builder_packets field) — pass each builder its packet "
                                "path; it must not re-read the reports the packet covers."
                            )
                except Exception as exc:
                    observe_packet_failure(work_dir, payload, "repair", exc)
            elif render_is_current(manifest):
                render = manifest.get("render") or {}
                contact = Path(str((render.get("contact_sheet") or {}).get("path") or ""))
                thumb = Path(str((render.get("contact_sheet_thumb") or {}).get("path") or ""))
                overview = thumb if (thumb and thumb.is_file()) else contact
                payload["read_images"] = [str(overview), str(work_dir / "render")]
                qa_command = (
                    f'{python} "{pipeline}" qa --work-dir "{work_dir}" '
                    f'--visual-review "{work_dir / "visual-review.json"}"'
                )
                if work_id_receipt_policy(manifest) == "allow-missing":
                    # policy is work-id state: next_command carries it so an agent
                    # following the command verbatim cannot re-hit the refusal
                    qa_command += " --receipt-policy allow-missing"
                payload["next_command"] = qa_command
                payload["notes"] = (
                    "Spawn student-presentation-suite:visual-critic WITHOUT a `name` "
                    "parameter — a named Agent call becomes a teammate whose agent_type is the name, "
                    "so SubagentStop never issues critic-execution.json and QA blocks forever. "
                    "Overview: read the cheap contact-sheet-thumb.jpg, not the full-size contact sheet; "
                    "the isolated critic Reads EVERY full-size page (its context never reaches this session). "
                    + (
                        "Degraded receipt policy for this work-id: wait for the critic to return "
                        "and confirm visual-review.json is valid — do NOT wait for "
                        "critic-execution.json, which this runtime cannot produce."
                        if work_id_receipt_policy(manifest) == "allow-missing"
                        else "Wait for critic-execution.json before QA."
                    )
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
                blocker_slides = slides_named_in_reports(
                    work_dir, ("pipeline-qa.json", "pre-qa-quality.json", "pre-qa-actual-content.json",
                               "pre-qa-rendered.json")
                )
                shards = builder_shards(blocker_slides, work_dir)
                if shards:
                    payload["builder_shards"] = shards
                    payload["notes"] += (
                        f" {len(blocker_slides)} blocker pages span {shards['parallel']} shards: after "
                        "`repair`, spawn one builder per shard in ONE message (see builder_shards). "
                        "Deck-level blockers without a slide number mean the whole deck is in scope — "
                        "use ONE builder reading the reports."
                    )
                # Builder Packet (v0.15 Batch 2): full-QA repair packets projected from
                # pipeline-qa.json, generated once the repair is recorded.
                try:
                    if blocker_slides and (work_dir / "pipeline-qa.json").is_file():
                        packets = _packet.prepare_packets(
                            work_dir, "repair", blocker_slides, ["pipeline-qa.json"]
                        )
                        if packets:
                            payload["builder_packets"] = packets
                            payload["notes"] += (
                                " Repair packets with the projected blockers are generated under "
                                "builder-packets/ (builder_packets field) — spawn each builder with "
                                "its packet path as the task input."
                            )
                except Exception as exc:
                    observe_packet_failure(work_dir, payload, "repair", exc)
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
    # Batch 2.1 observability: a benchmark can read how many packet generations
    # failed for this work dir (each one is a builder that fell back to the legacy
    # full-read context path and quietly gave back Batch 2's savings).
    payload["packet_fallback_count"] = len(packet_fallbacks(work_dir))
    return payload


def cmd_next(args: argparse.Namespace) -> int:
    """Tell the model what to read and which command to run. CD-1/CD-3/CD-4/CD-9."""
    payload = build_next_payload(args.work_dir.resolve())
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


