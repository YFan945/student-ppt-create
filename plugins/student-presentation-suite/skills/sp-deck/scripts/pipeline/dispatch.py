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
    RefusedError,
    execution_receipt,
    generator_changed_since_build,
    load_json,
    load_manifest,
    pptx_path,
    pre_qa_failed_current,
    render_is_current,
    sha256_file,
    work_id_receipt_policy,
)
from pipeline.deliverables import (  # noqa: E402
    deliverables_are_current,
    requested_prepared_deliverables,
)
from pipeline.scheduler import (  # noqa: E402
    builder_instance_reuse,
    builder_shards,
    observe_packet_failure,
    packet_fallbacks,
    page_files_by_slide,
    remaining_scaffold_slides,
    slides_named_in_reports,
)
from shared.quality_tiers import calibration_enabled, effective_shard_cap, tier_policy  # noqa: E402


def _high_leverage(work_dir: Path) -> list[int]:
    """The critic's <ids> slot: projected so the main session never opens the AD."""
    try:
        from calibration_preview import high_leverage_slides  # noqa: PLC0415

        return high_leverage_slides(work_dir / "art-direction.yaml")
    except Exception:
        return []


def _materialize_critic_previews(work_dir: Path) -> str:
    """Materialize the hash-bound critic preview map without relying on hooks.

    The runtime hook refreshes the map at critic spawn, but hooks do not fire in
    every runtime (the documented degrade ladder): without the map the critic
    template's first read (critic-preview-map.json) fails and the critic falls
    back to full-size render PNGs. The boundary materializes it deterministically;
    the hook stays a refresher and the write-path guard reads the same file.
    Returns "" on success, else the failure detail for the boundary notes.
    """
    scripts = ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import critic_preview  # noqa: PLC0415

        critic_preview.materialize(work_dir)
    except Exception as exc:  # Pillow missing or stale evidence: degrade, don't block the spawn
        return str(exc)[:200]
    return ""


def _current_critic_review(work_dir: Path, manifest: dict[str, Any]) -> bool:
    """True only when the existing independent review covers this exact render."""
    review_path = work_dir / "visual-review.json"
    if not review_path.is_file():
        return False
    try:
        review = load_json(review_path)
        if not isinstance(review, dict):
            return False
        from pptx_quality_gate_v071 import visual_review_schema_issues

        if any(item.get("severity") in {"critical", "major"} for item in visual_review_schema_issues(review)):
            return False
        render = manifest.get("render") or {}
        pages = render.get("pages") or []
        contact = render.get("contact_sheet") or {}
        if (
            review.get("pptx_sha256") != sha256_file(pptx_path(manifest))
            or review.get("contact_sheet_sha256") != contact.get("sha256")
            or review.get("page_sha256") != {
                str(index): item.get("sha256") for index, item in enumerate(pages, 1)
            }
        ):
            return False
        receipt = execution_receipt(
            work_dir, "critic", review_path, policy=work_id_receipt_policy(manifest)
        )
        if not receipt.get("degraded"):
            # 0.27.0：增量评审轮的 receipt 只覆盖 contact sheet + 变更页——与
            # qa 的范围检查同口径；非增量轮仍要求全页覆盖。
            scope_path = work_dir / "review-scope.json"
            scope = load_json(scope_path) if scope_path.is_file() else None
            changed = None
            if isinstance(scope, dict) and isinstance(scope.get("changed_slides"), list) and scope["changed_slides"]:
                changed = {int(item) for item in scope["changed_slides"]}
            for index, binding in enumerate([contact, *pages], 0):
                if index and changed is not None and index not in changed:
                    continue
                if receipt.get("reads", {}).get(binding.get("path")) != binding.get("sha256"):
                    return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RefusedError):
        return False


def _implemented_calibration_slides(work_dir: Path) -> list[int]:
    """Packet slides whose page modules exist and are no longer scaffold stubs.

    Read-only: resolves the active (or default) calibration set without writing
    packet bookkeeping, so a bare `next` call never creates builder state.
    """
    try:
        active = _packet.active_packet_descriptors(work_dir, "calibration")
        if active:
            slides = [int(slide) for slide in active[0]["slides"]]
        else:
            slides = [int(slide) for slide in _packet.default_calibration_slides(work_dir)]
    except Exception:
        return []
    if not slides:
        return []
    from calibration_preview import SCAFFOLD_MARKER, page_map  # noqa: PLC0415  (sibling module)

    available = page_map(work_dir)
    for slide in slides:
        path = available.get(slide)
        if path is None or SCAFFOLD_MARKER in path.read_text(encoding="utf-8"):
            return []
    return slides


REVIEW_SCOPE_NAME = "review-scope.json"


def _incremental_review_scope(work_dir: Path, manifest: dict[str, Any]) -> dict[str, Any] | None:
    """Changed-page set for an incremental critic round, or None for a full review.

    A prior review that does not bind the current render normally forces a FULL
    re-review. When it carries a page_sha256 map, the pages whose render PNG
    hash is unchanged need no second look: their verdicts are carried over and
    the critic re-reviews only the changed pages (0.27.0 — a one-page autofix
    used to cost a full-deck critic pass). None means "review everything":
    no prior review, no page map, or every page changed.
    """
    review_path = work_dir / "visual-review.json"
    if not review_path.is_file():
        return None
    try:
        prior = load_json(review_path)
        prior_pages = prior.get("page_sha256") if isinstance(prior, dict) else None
        if not isinstance(prior_pages, dict) or not prior_pages:
            return None
        pages = (manifest.get("render") or {}).get("pages") or []
        if not pages:
            return None
        current = {str(i): item.get("sha256") for i, item in enumerate(pages, 1)}
        changed = sorted(int(k) for k, sha in current.items() if prior_pages.get(k) != sha)
        unchanged = sorted(int(k) for k in current if prior_pages.get(k) == current[k])
        if not changed or not unchanged:
            return None
        return {
            "changed_slides": changed,
            "unchanged_slides": unchanged,
            "prior_review": str(review_path.resolve()),
            "prior_review_sha256": sha256_file(review_path),
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _persist_review_scope(work_dir: Path, scope: dict[str, Any]) -> Path:
    path = work_dir / REVIEW_SCOPE_NAME
    path.write_text(json.dumps(scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _try_autofix(work_dir: Path) -> dict[str, Any] | None:
    """Mechanical layout-swap fixes for the current review, or None for a builder.

    Best-effort by design: any failure (node missing, malformed review, script
    error) falls back to the repair builder — autofix must never make the
    pipeline more fragile than the round it replaces.
    """
    try:
        from pipeline.autofix import autofix_pending_repair

        return autofix_pending_repair(work_dir)
    except Exception:
        return None


def _dispatch_repair_builder(
    work_dir: Path, payload: dict[str, Any], manifest: dict[str, Any], basic: bool
) -> None:
    """Request the post-QA repair builder with the projected packet."""
    payload["agent"] = "student-presentation-suite:presentation-builder"
    payload["builder_mode"] = "repair"
    payload["notes"] = "repair is recorded; fix the blocker pages, then build → render → qa"
    try:
        blocker_slides = slides_named_in_reports(
            work_dir,
            ("pipeline-qa.json", "pre-qa-quality.json", "pre-qa-actual-content.json", "pre-qa-rendered.json"),
        )
        if (work_dir / "pipeline-qa.json").is_file():
            repair_targets = blocker_slides or sorted(page_files_by_slide(work_dir))
            packets = _packet.prepare_packets(
                work_dir, "repair", repair_targets, ["pipeline-qa.json"],
                single_builder=basic or not blocker_slides,
                max_parallel=effective_shard_cap(manifest.get("quality_level"), len(repair_targets)),
                convergence=repair_convergence(work_dir),
            )
            if packets:
                payload["builder_packets"] = packets
                payload["notes"] += (
                    " Repair packets with the projected blockers are generated under "
                    "builder-packets/ (builder_packets field) — pass each builder its packet "
                    "path; it must not re-read the reports the packet covers."
                )
    except Exception as exc:
        observe_packet_failure(work_dir, payload, "repair", exc)


def _dispatch_calibration_builder(work_dir: Path, payload: dict[str, Any]) -> None:
    """Request a calibration builder with the projected packet (v0.15 Batch 2)."""
    payload["agent"] = "student-presentation-suite:presentation-builder"
    payload["builder_mode"] = "calibration"
    payload["notes"] = (
        "spawn student-presentation-suite:presentation-builder mode=calibration with the absolute "
        "work-dir and the packet's slide ids (no `name`). It implements only those pages; the rest stay "
        "scaffolded so an early full build stays impossible. The MAIN session never edits "
        "pages/pNN-*.js itself. After BUILDER_DONE run calibration_preview.py."
    )
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


def build_next_payload(work_dir: Path) -> dict[str, Any]:
    """Compute the dispatch answer `next --json` prints (Batch 3 refactor).

    Extracted from cmd_next so `advance` can consult the same dispatch without
    duplicating it: agent boundaries are returned as-is, deterministic commands
    are executed by advance's loop."""
    manifest = load_manifest(work_dir)
    python = f'"{sys.executable}"'
    pipeline = HERE / "ppt_pipeline.py"
    if not manifest:
        validator = str(ROOT / "scripts" / "validate_slide_spec.py")
        payload = {
            "state": "(absent)",
            "read": [],
            "forbidden_to_read": [f"{ROOT / 'references'}/*.md"],
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
                    "research-backed deck: author the spec AFTER the validated research pack "
                    "exists — one pass, verified numbers in place; do NOT freeze a placeholder "
                    "spec and rewrite it when research lands (plan injects the evidence map and "
                    "E-ids itself; a second spec pass also forces re-validate + re-scaffold)",
                    "validate BEFORE plan: plan refuses without the --validation-report file",
                ],
            },
            "notes": (
                "intake first; do not grep plugin source — this command is the discovery API. "
                "Sequence when external facts are needed: spawn presentation-researcher from the "
                "MAIN session without `name` (the claim list comes from the Production Summary — "
                "no spec needed to spawn it), wait for a zero-blocker research-pack.json, THEN "
                "author slide-spec.yaml once from the validated pack (verified numbers in place; "
                "uncovered dimensions stay qualitative with caliber caveats). If "
                "research-pack.json exists in the work-dir, plan compiles evidence-map.json "
                "itself (do not pass --evidence-map). Freezing a placeholder spec before research "
                "and rewriting it afterwards is the most expensive duplication in this flow "
                "(2026-09-28 live)."
            ),
        }
    else:
        state = str(manifest.get("state") or "(absent)")
        policy = tier_policy(manifest.get("quality_level"))
        # 短 standard deck 跳过校准：页数冻结在 plan 时写进 manifest.scaffold.slides，
        # 续会话与首次分派据此得到同一个"校不校准"的决定。
        deck_pages = (manifest.get("scaffold") or {}).get("slides")
        calibrates = calibration_enabled(
            manifest.get("quality_level"), int(deck_pages) if deck_pages else None
        )
        basic = not calibrates
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
            elif not calibrates:
                remaining = remaining_scaffold_slides(work_dir)
                if not remaining:
                    payload["next_command"] = f'{python} "{pipeline}" build --work-dir "{work_dir}"'
                    payload["notes"] = f"{policy['tier']}: all pages implemented; run the deterministic build."
                else:
                    payload["agent"] = "student-presentation-suite:presentation-builder"
                    payload["builder_mode"] = "initial"
                    payload["notes"] = (
                        f"{policy['tier']}: implement all scaffolded pages from the Art Direction; "
                        "final independent visual review remains required."
                    )
                    # D1: fast stays single-builder below the page line (coordination
                    # costs more than one builder's context), but a long deck split
                    # across one instance inflates its context past the point of no
                    # return — above the line fast shards to 2 like standard.
                    fast_cap = effective_shard_cap(manifest.get("quality_level"), len(remaining))
                    if fast_cap > 1:
                        shards = builder_shards(remaining, work_dir, max_parallel=fast_cap)
                        if shards:
                            payload["builder_shards"] = shards
                            payload["notes"] += (
                                f" {len(remaining)} pages exceed the fast shard line: spawn all "
                                f"{shards['parallel']} shards in ONE message (see builder_shards) so "
                                "no single builder carries the whole deck."
                            )
                    try:
                        packets = _packet.prepare_packets(
                            work_dir, "initial", remaining, single_builder=fast_cap <= 1,
                            max_parallel=fast_cap,
                        )
                        if packets:
                            payload["builder_packets"] = packets
                    except Exception as exc:
                        observe_packet_failure(work_dir, payload, "initial", exc)
            else:
                # Resume-safe calibration dispatch (2026-09-17): a live session was
                # cut mid calibration-fix round and `next` answered a raw `build`,
                # teaching the MAIN session to edit page modules directly — the one
                # flow builder_guard forbids. Dispatch on what calibration evidence
                # exists so an interrupted session resumes at the right step.
                calibration_manifest = work_dir / "calibration" / "calibration-manifest.json"
                calibration_rendered = bool(list((work_dir / "calibration" / "render").glob("calibration-*.png")))
                if not calibration_manifest.is_file():
                    # 0.25.4: calibration-manifest.json is only written by a SUCCESSFUL
                    # preview, so keying the dispatch solely on it made advance
                    # re-request a calibration builder after every BUILDER_DONE — the
                    # first preview could never be auto-scheduled and SKILL step 8's
                    # "advance runs the helper" was unreachable (run-14 live). When the
                    # packet's pages are already implemented (exist, no scaffold
                    # marker), the correct next step is the preview, not a new builder.
                    pending_preview = _implemented_calibration_slides(work_dir)
                    if pending_preview:
                        slide_args = " ".join(str(slide) for slide in pending_preview)
                        payload["next_command"] = (
                            f'{python} "{HERE / "calibration_preview.py"}" --work-dir "{work_dir}" '
                            f"--slides {slide_args} --json"
                        )
                        payload["notes"] = (
                            "calibration pages are implemented but no preview manifest exists yet: run "
                            "calibration_preview.py (advance executes it when this is the next command), then hand "
                            "the preview to the independent visual-critic (step 8)."
                        )
                    else:
                        _dispatch_calibration_builder(work_dir, payload)
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
                    rounds = int((manifest.get("calibration") or {}).get("rounds") or 0)
                    # Tier budget: standard spends 1 calibration round, rigorous 2.
                    # Once spent, remaining majors are carried as recorded risk
                    # instead of another builder+critic cycle.
                    budget_spent = (
                        not review["ok"]
                        and review.get("action") == "builder"
                        and rounds >= policy["calibration_max_rounds"]
                    )
                    if not review["ok"] and not budget_spent:
                        # 0.26.0: not-ok is deterministic only (stale evidence → rerun the
                        # preview; palette violation / style summary missing → targeted
                        # builder repair). The critic no longer gates calibration — it
                        # reviews the deck once at the production boundary.
                        payload["calibration"] = {
                            "slides": review["slides"],
                            "pptx": str(work_dir / CALIBRATION_DIR_NAME / "calibration.pptx"),
                            "render": [
                                str(path)
                                for path in sorted((work_dir / CALIBRATION_DIR_NAME / "render").glob("calibration-*.png"))
                            ],
                            "manifest": str(work_dir / CALIBRATION_DIR_NAME / CALIBRATION_MANIFEST_NAME),
                            "status": review["reason"],
                        }
                        if review.get("action") == "preview":
                            slide_args = " ".join(str(slide) for slide in review["slides"])
                            payload["next_command"] = (
                                f'{python} "{HERE / "calibration_preview.py"}" '
                                f'--work-dir "{work_dir}" --slides {slide_args} --json'
                            )
                            payload["notes"] = (
                                f"Calibration evidence is stale: {review['reason']}. Rerun the exact "
                                "preview command above; the deterministic gates re-verify the current page bytes."
                            )
                        else:
                            repair_slides = review.get("repair_slides") or review["slides"]
                            payload["agent"] = "student-presentation-suite:presentation-builder"
                            payload["builder_mode"] = "calibration"
                            calibration_reports = [
                                report
                                for report in [work_dir / "calibration" / "palette-report.json"]
                                if report.is_file()
                            ]
                            packets = _packet.prepare_packets(
                                work_dir, "calibration", repair_slides,
                                calibration_reports,
                            )
                            if packets:
                                payload["builder_packet"] = packets[0]
                            payload["notes"] = (
                                f"Calibration is not deterministically green: {review['reason']}. "
                                f"Spawn presentation-builder (no `name`) with mode=calibration for slides "
                                f"{repair_slides} using the packet above, then rerun calibration_preview.py "
                                "for the complete calibration set."
                            )
                            if review.get("review_advisory", {}).get("blockers"):
                                payload["notes"] += (
                                    " Advisory (non-gating): an existing calibration review file reports "
                                    f"{len(review['review_advisory']['blockers'])} blocker(s) — fold them into "
                                    "this repair where they are real."
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
                            shards = builder_shards(
                                remaining, work_dir,
                                max_parallel=effective_shard_cap(manifest.get("quality_level"), len(remaining)),
                            )
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
                                packets = _packet.prepare_packets(
                                    work_dir, "initial", remaining,
                                    max_parallel=effective_shard_cap(manifest.get("quality_level"), len(remaining)),
                                )
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
                            if budget_spent:
                                payload["notes"] = (
                                    f"Calibration tier budget spent ({rounds}/"
                                    f"{policy['calibration_max_rounds']} rounds); remaining review "
                                    f"findings carried as recorded risk: {review['reason']}. "
                                ) + payload["notes"]
        elif state == "producing":
            pending_repair = bool((manifest.get("build") or {}).get("pending_repair"))
            exhausted = pre_qa_failed_current(manifest) and int(
                (manifest.get("pre_qa") or {}).get("rounds") or 0
            ) >= MAX_PRE_QA_REBUILDS
            if exhausted and not pending_repair:
                payload["next_command"] = (
                    f'{python} "{pipeline}" repair --work-dir "{work_dir}" '
                    '--reason "Pre-QA retry budget exhausted; repair all deterministic blockers"'
                )
                payload["notes"] = "Pre-QA is still blocked; register a budgeted repair before rebuilding."
            elif (pending_repair or pre_qa_failed_current(manifest)) and generator_changed_since_build(manifest):
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
                pre_qa_reports = _packet.pre_qa_report_paths(work_dir)
                payload["pre_qa"]["reports"] = [str(path) for path in pre_qa_reports]
                fixable = slides_named_in_reports(work_dir, tuple(str(path) for path in pre_qa_reports))
                shards = builder_shards(fixable, work_dir) if not basic else None
                if shards:
                    payload["builder_shards"] = shards
                # Builder Packet (v0.15 Batch 2): repair packet per instance, blockers
                # projected from the pre-QA reports instead of the builder re-reading them.
                try:
                    # 全量投影（pre_qa_report_paths 单一属主）：只挑几个名字会把
                    # pre-qa-static-risk / pre-qa-structural-contract-* 挡在 packet
                    # 之外，而 hook 又禁读它们——两头堵死（2026-09-28 live）。
                    repair_targets = fixable or sorted(page_files_by_slide(work_dir))
                    packets = _packet.prepare_packets(
                        work_dir, "repair", repair_targets, pre_qa_reports,
                        single_builder=basic or not fixable,
                        max_parallel=effective_shard_cap(manifest.get("quality_level"), len(repair_targets)),
                    )
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
                # 0.26.0 autofix: when EVERY pending finding is a mechanical layout swap
                # (repair_level=implementation, fix names a library id), the pipeline
                # applies them itself — a builder instance for one-line data edits is the
                # most expensive way to change a string. Mixed/creative findings still
                # take the builder path below.
                autofix_report = _try_autofix(work_dir)
                if autofix_report:
                    payload["autofix"] = autofix_report
                    payload["next_command"] = f'{python} "{pipeline}" build --work-dir "{work_dir}"'
                    payload["notes"] = (
                        f"autofix applied {autofix_report.get('applied_count')} mechanical layout fix(es) "
                        f"(report: {Path(work_dir) / 'autofix-report.json'}): rebuild → render → a FRESH "
                        "independent review verifies them; do NOT spawn a builder for these findings."
                    )
                else:
                    _dispatch_repair_builder(work_dir, payload, manifest, basic)
            elif (
                render_is_current(manifest)
                and requested_prepared_deliverables(manifest)
                and not deliverables_are_current(manifest)
            ):
                payload["next_command"] = (
                    f'{python} "{pipeline}" prepare-deliverables --work-dir "{work_dir}"'
                )
                payload["notes"] = (
                    "Generate and hash-bind every confirmed support/export deliverable before "
                    "spawning the critic. advance executes this deterministic step automatically."
                )
                payload["prepare_deliverables"] = requested_prepared_deliverables(manifest)
            elif render_is_current(manifest):
                # The isolated critic reads the contact sheet and every page.
                # Sending the same images to the orchestrating session doubles
                # visual context without adding an independent judgment.
                payload["read_images"] = []
                qa_command = (
                    f'{python} "{pipeline}" qa --work-dir "{work_dir}" '
                    f'--visual-review "{work_dir / "visual-review.json"}"'
                )
                if work_id_receipt_policy(manifest) == "allow-missing":
                    # policy is work-id state: next_command carries it so an agent
                    # following the command verbatim cannot re-hit the refusal
                    qa_command += " --receipt-policy allow-missing"
                payload["next_command"] = qa_command
                if _current_critic_review(work_dir, manifest):
                    payload["read_images"] = []
                    payload["notes"] = (
                        "A current independent visual review and receipt already cover this render. "
                        "Run QA using that report; do not spawn another Visual Critic."
                    )
                    payload["visual_evidence_reused"] = True
                else:
                    preview_failure = _materialize_critic_previews(work_dir)
                    # 0.27.0 增量评审：修复轮后只有变更页需要重看——未变更页的
                    # 渲染 PNG 哈希与上一轮评审一致，判定逐字继承（carried_over）。
                    # 全量评审只在首轮或全部页都变更时发生。
                    scope = _incremental_review_scope(work_dir, manifest)
                    if scope:
                        _persist_review_scope(work_dir, scope)
                    payload["notes"] = (
                        "Spawn student-presentation-suite:visual-critic WITHOUT a `name` "
                        "parameter — a named Agent call becomes a teammate whose agent_type is the name, "
                        "so SubagentStop never issues critic-execution.json and QA blocks forever. "
                        "A scope=production critic-preview-map.json with compressed previews is "
                        "materialized under the work-dir (the runtime hook refreshes it at spawn when "
                        "hooks are enabled); the critic reads the map, not raw render paths. "
                        "Read the mapped overview and EVERY mapped page preview; raw render PNGs "
                        "are needed only when a preview is missing or illegible. "
                        + (
                            "Degraded receipt policy for this work-id: wait for the critic to return "
                            "and confirm visual-review.json is valid — do NOT wait for "
                            "critic-execution.json, which this runtime cannot produce."
                            if work_id_receipt_policy(manifest) == "allow-missing"
                            else "Wait for critic-execution.json before QA."
                        )
                    )
                    if scope:
                        payload["incremental_review"] = scope
                        payload["notes"] += (
                            f" INCREMENTAL REVIEW: only slides {scope['changed_slides']} changed since the "
                            f"prior review ({scope['prior_review']}); slides {scope['unchanged_slides']} are "
                            "byte-identical. Re-review the changed pages and the contact sheet, copy the "
                            "prior entries verbatim for unchanged slides adding \"carried_over\": true, and "
                            "write the FULL page_sha256 mapping for the current render. The receipt "
                            "coverage check accepts this scope."
                        )
                    if preview_failure:
                        payload["notes"] += (
                            f" Preview materialization failed ({preview_failure}); run "
                            f'{python} "{ROOT / "scripts" / "critic_preview.py"}" --work-dir "{work_dir}" '
                            "--json before spawning, or the critic must read the render PNGs directly."
                        )
                    payload["agent"] = "student-presentation-suite:visual-critic"
                    payload["high_leverage_slides"] = _high_leverage(work_dir)
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
            if (
                qa.get("ok")
                and requested_prepared_deliverables(manifest)
                and not deliverables_are_current(manifest)
            ):
                payload["next_command"] = (
                    f'{python} "{pipeline}" prepare-deliverables --work-dir "{work_dir}"'
                )
                payload["notes"] = (
                    "A confirmed deliverable changed or disappeared after QA. Recreate and bind it; "
                    "this invalidates the old QA result and returns the pipeline to producing."
                )
                payload["prepare_deliverables"] = requested_prepared_deliverables(manifest)
            elif qa.get("ok"):
                payload["next_command"] = f'{python} "{pipeline}" complete --work-dir "{work_dir}"'
            elif render_is_current(manifest) and (work_dir / "pipeline-qa.json").is_file() and any(
                item.get("code") == "visual_review_schema_invalid"
                for item in (load_json(work_dir / "pipeline-qa.json").get("problems") or [])
                if isinstance(item, dict)
            ):
                # A malformed critic report cannot be fixed by editing pages.
                # Correct/revalidate it before registering a deck repair round.
                payload["next_command"] = (
                    f'{python} "{pipeline}" qa --work-dir "{work_dir}" '
                    f'--visual-review "{work_dir / "visual-review.json"}"'
                )
                payload["notes"] = "Correct the critic report contract, then rerun QA; do not rebuild or spend a Builder repair round."
                if not _current_critic_review(work_dir, manifest):
                    detail = _materialize_critic_previews(work_dir)
                    payload["agent"] = "student-presentation-suite:visual-critic"
                    payload["notes"] += " Spawn visual-critic without a name, using critic-preview-map.json and its schema_path; correct the report against the same current render."
                    if detail:
                        payload["notes"] += f" Preview failure: {detail}."
            else:
                payload["next_command"] = (
                    f'{python} "{pipeline}" repair --work-dir "{work_dir}" --reason "<summary>"'
                )
                payload["notes"] = "fix every blocker page in one parallel Edit round, then build + qa"
                blocker_slides = slides_named_in_reports(
                    work_dir, ("pipeline-qa.json", "pre-qa-quality.json", "pre-qa-actual-content.json",
                               "pre-qa-rendered.json")
                )
                shards = builder_shards(
                    blocker_slides, work_dir,
                    max_parallel=effective_shard_cap(manifest.get("quality_level"), len(blocker_slides)),
                )
                if shards:
                    payload["builder_shards"] = shards
                    payload["notes"] += (
                        f" {len(blocker_slides)} blocker pages span {shards['parallel']} shards: after "
                        "`repair`, spawn one builder per shard in ONE message (see builder_shards). "
                        "Deck-level blockers without a slide number mean the whole deck is in scope — "
                        "use ONE builder reading the reports."
                    )
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
    elif manifest and str(manifest.get("state") or "") == "producing" and pre_qa_failed_current(manifest) and " repair " not in payload["next_command"]:
        # the pre-QA fix path is a build-stage rule set: builder edits, rebuild, no repair
        action = "build"
    else:
        for candidate in ("build", "render", "prepare-deliverables", "qa", "repair", "complete"):
            if f" {candidate} " in payload["next_command"]:
                action = candidate.replace("-", "_")
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


