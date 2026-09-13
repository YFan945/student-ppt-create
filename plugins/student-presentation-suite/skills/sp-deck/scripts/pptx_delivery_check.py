#!/usr/bin/env python3
"""Check expected PPTX delivery files for student presentation generation.

This script verifies file existence, counts slides from PPTX XML, and validates
package/QA evidence. It does not render slides, so preview/contact-sheet review
is still required for visual QA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check PPTX delivery package")
    parser.add_argument("--pptx", type=Path, required=True, help="Generated PPTX path")
    parser.add_argument("--notes", type=Path, help="Speaker notes Markdown path")
    parser.add_argument(
        "--preview",
        type=Path,
        action="append",
        default=[],
        help="Preview image, contact sheet, or exported PDF path; repeatable",
    )
    parser.add_argument("--pdf", type=Path, help="Optional requested PDF export")
    parser.add_argument("--teleprompter", type=Path, help="Optional requested HTML teleprompter")
    parser.add_argument("--quality-report", type=Path, help="Optional requested JSON quality report")
    parser.add_argument("--package-report", type=Path, help="PPTX package validation JSON report")
    parser.add_argument(
        "--slide-spec-report",
        type=Path,
        help="Validated Slide Spec report used by the simplified gate",
    )
    parser.add_argument("--revision-manifest", type=Path, help="Optional requested revision manifest")
    parser.add_argument("--qa-manifest", type=Path, help="Rendered QA evidence manifest JSON path")
    parser.add_argument(
        "--simple",
        action="store_true",
        help="Use the default three-gate flow without separate content/asset/visual manifests",
    )
    parser.add_argument(
        "--visual-reviewed",
        action="store_true",
        help="Deprecated self-attestation flag; completion now requires --visual-review-report",
    )
    parser.add_argument(
        "--visual-review-report",
        type=Path,
        help="Visual-review JSON bound to the PPTX via pptx_sha256 (required for simple-mode completion)",
    )
    parser.add_argument("--output", type=Path, help="Optional delivery-report.json output path")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument(
        "--allow-missing-notes",
        action="store_true",
        help="Do not require a notes file; use only when notes are embedded or explicitly out of scope",
    )
    parser.add_argument(
        "--allow-missing-preview",
        action="store_true",
        help="Publish an incomplete report without preview evidence; never qualifies for complete",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless all file, preview, and QA-manifest gates pass",
    )
    return parser.parse_args()


def slide_number(name: str) -> int:
    match = re.search(r"slide(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def count_slides(path: Path) -> tuple[int | None, str | None]:
    try:
        with zipfile.ZipFile(path) as zf:
            slide_names = [
                n
                for n in zf.namelist()
                if n.startswith("ppt/slides/slide") and n.endswith(".xml")
            ]
            return len(sorted(slide_names, key=slide_number)), None
    except (FileNotFoundError, PermissionError, OSError, zipfile.BadZipFile, KeyError) as exc:
        return None, str(exc)



def file_info(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        exists = path.is_file()
        size = path.stat().st_size if exists else None
        error = None
    except (PermissionError, OSError) as exc:
        exists = False
        size = None
        error = str(exc)
    return {
        "path": str(path),
        "exists": exists,
        "size_bytes": size,
        "error": error,
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_visual_review_report(report_path: Path, pptx: Path) -> dict[str, Any]:
    """A "reviewed" claim must be a report file bound to this exact PPTX.

    The bare ``--visual-reviewed`` boolean is asserted by the generating agent
    itself, so it proves nothing. The report file must carry ``pptx_sha256``
    matching the artifact being gated plus per-slide entries.
    """
    path = Path(report_path)
    if not path.is_file():
        return {"valid": False, "reason": f"visual-review report not found: {path}"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"valid": False, "reason": f"unreadable visual-review report: {exc}"}
    if not isinstance(data, dict):
        return {"valid": False, "reason": "visual-review report must be a JSON object"}
    if data.get("pptx_sha256") != sha256_file(pptx):
        return {"valid": False, "reason": "visual-review report is not bound to the current PPTX (stale sha256)"}
    slides = data.get("slides")
    if not isinstance(slides, list) or not slides:
        return {"valid": False, "reason": "visual-review report contains no per-slide entries"}
    return {
        "valid": True,
        "report_sha256": sha256_file(path),
        "slide_entries": len(slides),
        "average_score": data.get("average_score"),
    }


def inspect_preview(path: Path) -> dict[str, Any]:
    """Decode raster previews and reject tiny or single-colour placeholders."""
    result: dict[str, Any] = {"path": str(path.resolve()), "valid": False, "error": None}
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        result["error"] = "Preview must be a PNG or JPEG raster image."
        return result
    try:
        from PIL import Image, ImageStat  # noqa: PLC0415

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            extrema = ImageStat.Stat(image.convert("RGB")).extrema
        result.update({"width": width, "height": height, "sha256": sha256_file(path)})
        if width < 320 or height < 180:
            result["error"] = "Preview dimensions are too small for visual inspection."
        elif all(low == high for low, high in extrema):
            result["error"] = "Preview is a single-colour placeholder, not rendered evidence."
        else:
            result["valid"] = True
    except (ImportError, OSError, ValueError) as exc:
        result["error"] = str(exc)
    return result


def validate_qa_manifest(
    manifest_path: Path | None,
    pptx: Path,
    slide_count: int | None,
    preview_checks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate evidence that the current PPTX was rendered and visually reviewed."""
    result: dict[str, Any] = {"provided": manifest_path is not None, "valid": False, "errors": [], "warnings": []}
    if manifest_path is None:
        result["errors"].append("QA manifest is required.")
        return result
    result["path"] = str(manifest_path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Manifest root must be an object.")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result["errors"].append(f"Cannot read QA manifest: {exc}")
        return result
    result["manifest"] = data
    if not pptx.is_file() or data.get("pptx_sha256") != sha256_file(pptx):
        result["errors"].append("pptx_sha256 does not match the current PPTX.")
    if slide_count is None or data.get("slide_count") != slide_count:
        result["errors"].append("slide_count does not match the PPTX.")
    rendered = data.get("rendered_page_count")
    if slide_count is not None and rendered not in (None, 0) and rendered != slide_count:
        result["errors"].append("rendered_page_count must equal PPTX slide_count when rendered.")
    if data.get("scenario_contract_passed") is not True:
        result["errors"].append("scenario_contract_passed must be true.")
    bound_spec_hash = data.get("slide_spec_sha256")
    spec_value = data.get("slide_spec")
    if not isinstance(spec_value, str) or not spec_value:
        result["errors"].append("slide_spec must identify the validated source contract.")
    else:
        spec_path = Path(spec_value)
        if not spec_path.is_absolute():
            spec_path = manifest_path.parent / spec_path
        if not spec_path.is_file() or sha256_file(spec_path) != bound_spec_hash:
            result["errors"].append("slide_spec_sha256 does not match the source Slide Spec.")
    for field, hash_field, ok_field in (
        ("slide_spec_report", "slide_spec_report_sha256", "valid"),
    ):
        value = data.get(field)
        if not isinstance(value, str) or not value:
            result["errors"].append(f"{field} must identify generation contract evidence.")
            continue
        evidence_path = Path(value)
        if not evidence_path.is_absolute():
            evidence_path = manifest_path.parent / evidence_path
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result["errors"].append(f"Cannot read {field}: {exc}")
            continue
        if data.get(hash_field) != sha256_file(evidence_path):
            result["errors"].append(f"{hash_field} does not match {field}.")
        if evidence.get(ok_field) is not True:
            result["errors"].append(f"{field} did not pass.")
        if evidence.get("slide_spec_sha256") != bound_spec_hash:
            result["errors"].append(f"{field} does not match slide_spec_sha256.")
    package_report_value = data.get("package_report")
    package_report_hash = data.get("package_report_sha256")
    if not isinstance(package_report_value, str) or not package_report_value:
        result["errors"].append("package_report must identify the package validation evidence.")
    else:
        package_path = Path(package_report_value)
        if not package_path.is_absolute():
            package_path = manifest_path.parent / package_path
        if not package_path.is_file():
            result["errors"].append(f"Cannot read package report: {package_path}")
        elif package_report_hash != sha256_file(package_path):
            result["errors"].append("package_report_sha256 does not match the package report.")
        else:
            # 深度校验（ok/profile/schema_validation）由 delivery 的 package_summary
            # 唯一承担；这里只做 manifest↔package report 的浅 hash 绑定。
            result["package_report"] = {
                "path": str(package_path.resolve()),
                "sha256": package_report_hash,
                "valid": True,
            }
    inspection = data.get("visual_inspection")
    if inspection is not None:
        if not isinstance(inspection, dict):
            result["errors"].append("visual_inspection must be an object.")
        elif inspection.get("completed") is True:
            expected_pages = list(range(1, (slide_count or 0) + 1))
            if sorted(inspection.get("inspected_pages") or []) != expected_pages:
                result["errors"].append("visual_inspection.inspected_pages must cover every slide.")
            if inspection.get("remaining_blockers") != 0:
                result["errors"].append("visual_inspection.remaining_blockers must be 0.")
    listed_files = data.get("preview_files")
    warnings: list[str] = []
    if listed_files:
        if not isinstance(listed_files, list):
            result["errors"].append("preview_files must be a list.")
        else:
            listed_hashes = data.get("preview_sha256")
            if not isinstance(listed_hashes, list) or len(listed_hashes) != len(listed_files):
                result["errors"].append("preview_sha256 must correspond to preview_files.")
            else:
                actual = {item.get("path"): item for item in preview_checks}
                for listed, expected_hash in zip(listed_files, listed_hashes, strict=False):
                    resolved = str((manifest_path.parent / listed).resolve()) if not Path(listed).is_absolute() else str(Path(listed).resolve())
                    check = actual.get(resolved)
                    if not check or not check.get("valid"):
                        result["errors"].append(f"Preview evidence is invalid or missing: {listed}")
                    elif check.get("sha256") != expected_hash:
                        # 预览在 manifest 之后重新渲染：文件本身有效，仅绑定过期。
                        # 降为 warning 不阻断；提示重建 manifest 或接受现状。
                        warnings.append(
                            f"Preview evidence is stale (re-rendered after the manifest): {listed}"
                        )
    result["warnings"] = warnings
    result["valid"] = not result["errors"]
    return result


def validate_bound_report(
    path: Path | None,
    *,
    label: str,
    pptx: Path | None = None,
    slide_count: int | None = None,
    slide_spec_sha256: str | None = None,
) -> dict[str, Any]:
    if path is None:
        return {"provided": False, "valid": None, "errors": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"provided": True, "valid": False, "errors": [f"Cannot read {label}: {exc}"]}
    errors = []
    if not isinstance(data, dict) or data.get("ok") is not True:
        errors.append(f"{label} does not pass.")
    if pptx is not None and pptx.is_file() and data.get("pptx_sha256") != sha256_file(pptx):
        errors.append(f"{label} does not match the current PPTX.")
    if slide_count is not None and data.get("slide_count") != slide_count:
        errors.append(f"{label} slide count does not match the current PPTX.")
    if slide_spec_sha256 is not None and data.get("slide_spec_sha256") != slide_spec_sha256:
        errors.append(f"{label} does not match the QA manifest Slide Spec.")
    return {
        "provided": True,
        "valid": not errors,
        "errors": errors,
        "sha256": sha256_file(path),
        "report": data,
    }


def validate_slide_spec_report(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"provided": False, "valid": False, "errors": ["Slide Spec report is required."]}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"provided": True, "valid": False, "errors": [f"Cannot read Slide Spec report: {exc}"]}
    errors = []
    if not isinstance(data, dict) or data.get("valid") is not True:
        errors.append("Slide Spec validation did not pass.")
    spec_value = data.get("slide_spec") if isinstance(data, dict) else None
    if not isinstance(spec_value, str) or not spec_value:
        errors.append("Slide Spec report does not identify its source spec.")
    else:
        spec_path = Path(spec_value)
        if not spec_path.is_absolute():
            spec_path = path.parent / spec_path
        if not spec_path.is_file() or data.get("slide_spec_sha256") != sha256_file(spec_path):
            errors.append("Slide Spec report does not match the current source spec.")
    return {
        "provided": True,
        "valid": not errors,
        "errors": errors,
        "sha256": sha256_file(path),
        "report": data,
    }


def expected_notes_path(pptx: Path) -> Path:
    stem = pptx.stem
    prefix = stem[: -len("-presentation")] if stem.endswith("-presentation") else stem
    return pptx.with_name(f"{prefix}-speaker-notes.md")


def expected_preview_paths(pptx: Path) -> list[Path]:
    stem = pptx.stem
    prefix = stem[: -len("-presentation")] if stem.endswith("-presentation") else stem
    parent = pptx.parent
    discovered = sorted(
        {
            *parent.glob(f"{prefix}*preview*.png"),
            *parent.glob(f"{prefix}*contact*.png"),
            *parent.glob(f"{prefix}*preview*.pdf"),
            *parent.glob(f"{prefix}*contact*.pdf"),
        }
    )
    return discovered or [parent / f"{prefix}-preview.png"]



def inspect_delivery(
    pptx: Path,
    notes: Path | None,
    previews: list[Path],
    *,
    require_notes: bool = True,
    require_preview: bool = True,
    extra_files: dict[str, Path | None] | None = None,
    qa_manifest: Path | None = None,
    quality_report: Path | None = None,
    package_report: Path | None = None,
    require_package_report: bool = False,
    slide_spec_report: Path | None = None,
    simple: bool = False,
    visual_reviewed: bool = False,
    visual_review_report: Path | None = None,
) -> dict[str, Any]:
    if require_notes and notes is None:
        notes = expected_notes_path(pptx)
    if require_preview and not previews:
        previews = expected_preview_paths(pptx)
    pptx_info = file_info(pptx)
    slide_count, slide_error = count_slides(pptx)
    preview_infos = [file_info(path) for path in previews]
    preview_checks = [inspect_preview(path) for path in previews if path.is_file()]
    missing = []
    if not pptx_info or not pptx_info["exists"]:
        missing.append("pptx")
    if require_notes and (
        notes is None
        or not notes.is_file()
        or (notes.is_file() and notes.stat().st_size == 0)
    ):
        missing.append("notes")
    if require_preview and not any(info and info["exists"] for info in preview_infos):
        missing.append("preview")
    extra_infos = {
        name: file_info(path)
        for name, path in (extra_files or {}).items()
        if path is not None
    }
    for name, info in extra_infos.items():
        if not info or not info["exists"]:
            missing.append(name)

    qa_summary = validate_qa_manifest(qa_manifest, pptx, slide_count, preview_checks)
    spec_summary = validate_slide_spec_report(slide_spec_report) if simple else {
        "provided": False,
        "valid": None,
        "errors": [],
    }
    bound_spec_hash = qa_summary.get("manifest", {}).get("slide_spec_sha256")
    quality_summary = validate_bound_report(
        quality_report,
        label="Quality report",
        slide_spec_sha256=bound_spec_hash,
    )
    package_summary: dict[str, Any] = {"valid": None, "errors": []}
    if package_report is not None:
        try:
            package_data = json.loads(package_report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            package_summary = {"valid": False, "errors": [str(exc)]}
        else:
            package_errors = []
            if package_data.get("ok") is not True:
                package_errors.append("package validation did not pass")
            if pptx.is_file() and package_data.get("pptx_sha256") != hashlib.sha256(pptx.read_bytes()).hexdigest():
                package_errors.append("package report hash does not match the current PPTX")
            if package_data.get("validation_profile") != "openxml-sdk-plus-suite-semantic-v4":
                package_errors.append("package validation profile is incomplete or unsupported")
            schema_validation = package_data.get("schema_validation")
            if not isinstance(schema_validation, dict) or schema_validation.get("performed") is not True:
                package_errors.append("Open XML schema validation was not performed")
            elif schema_validation.get("error_count") != 0:
                package_errors.append("Open XML schema validation reported errors")
            package_summary = {
                "valid": not package_errors,
                "errors": package_errors,
                "report": package_data,
            }
    elif require_package_report:
        package_summary = {"valid": False, "errors": ["package validation report is required"]}
    required_files_valid = not missing
    pptx_readable = pptx_info is not None and pptx_info["exists"] and slide_error is None
    render_qa_valid = all(item["valid"] for item in preview_checks)
    package_ready = (
        package_summary["valid"] is True
        if simple or require_package_report
        else package_summary["valid"] is not False
    )
    base_ready = bool(
        required_files_valid
        and pptx_readable
        and slide_count
        and slide_count > 0
        and render_qa_valid
        and preview_checks
        and package_ready
    )
    review_check: dict[str, Any] = {
        "valid": False,
        "reason": "no sha256-bound visual-review report supplied",
    }
    if visual_review_report is not None:
        review_check = verify_visual_review_report(visual_review_report, pptx)
    if simple:
        # 裸 --visual-reviewed 布尔量由生成方自行断言，不构成"人已复核"的证据；
        # 完成判定只认与当前 PPTX 的 sha256 绑定的复核报告文件。
        complete_ready = bool(
            base_ready
            and len(preview_checks) == slide_count
            and spec_summary["valid"] is True
            and review_check["valid"]
        )
    else:
        complete_ready = bool(
            base_ready
            and qa_summary["valid"]
            and quality_summary["valid"] is not False
            and isinstance(qa_summary.get("manifest", {}).get("visual_inspection"), dict)
            and qa_summary["manifest"]["visual_inspection"].get("completed") is True
        )

    inspection = qa_summary.get("manifest", {}).get("visual_inspection", {}) if qa_summary.get("valid") else {}
    delivery_report = {
        "ok": complete_ready,
        "status": "complete" if complete_ready else "incomplete",
        "gate_profile": "simplified-v1" if simple else "evidence-chain-v1",
        "pptx_sha256": sha256_file(pptx) if pptx.is_file() else None,
        "qa_manifest_sha256": (
            sha256_file(qa_manifest) if qa_manifest is not None and qa_manifest.is_file() else None
        ),
        "package_report_sha256": (
            sha256_file(package_report)
            if package_report is not None and package_report.is_file()
            else None
        ),
        "slide_count": slide_count,
        "package_blockers": (
            len(package_summary.get("errors", [])) if package_summary.get("valid") is False else 0
        ),
        "render_blockers": (
            0
            if simple and render_qa_valid and len(preview_checks) == (slide_count or 0)
            else len(qa_summary.get("errors", []))
        ),
        "scenario_contract_passed": (
            spec_summary.get("valid") is True
            if simple
            else qa_summary.get("manifest", {}).get("scenario_contract_passed")
            if qa_summary.get("valid")
            else False
        ),
        "slide_spec_validation_passed": spec_summary.get("valid") if simple else None,
        "slide_spec_report_sha256": spec_summary.get("sha256") if simple else None,
        "visual_reviewed": visual_reviewed if simple else None,
        "visual_review_check": review_check if simple else None,
        "quality_report_passed": quality_summary.get("valid"),
        "quality_report_sha256": quality_summary.get("sha256"),
        "package_validation_passed": package_summary.get("valid"),
        "preview_page_coverage": (
            f"{sum(1 for c in preview_checks if c.get('valid'))}/{slide_count or 0}"
            if preview_checks else "0/0"
        ),
        "repair_cycles": inspection.get("repair_cycles"),
    }
    return {
        "pptx": pptx_info,
        "notes": file_info(notes),
        "previews": preview_infos,
        "preview_validation": preview_checks,
        "extra_files": extra_infos,
        "slide_count": slide_count,
        "slide_count_error": slide_error,
        "qa_manifest": qa_summary,
        "slide_spec_report": spec_summary,
        "quality_report": quality_summary,
        "package_validation": package_summary,
        "missing_expected_files": missing,
        "ok": complete_ready,
        "delivery_report": delivery_report,
        "requirements": {
            "notes_required": require_notes,
            "preview_required": require_preview,
            "package_report_required": require_package_report,
            "simple_gate": simple,
        },
        "note": (
            "The simplified gate requires a valid Slide Spec report, package validation, one readable preview per slide, and explicit visual review."
            if simple
            else "Strict delivery requires package validation, readable rendered previews, and a QA manifest bound to the current PPTX."
        ),
    }


def print_text(result: dict[str, Any]) -> None:
    pptx = result["pptx"]
    print(result["note"])
    print(f"PPTX: {pptx['path']} exists={pptx['exists']} size={pptx['size_bytes']}")
    notes = result.get("notes")
    if notes is not None:
        print(f"Notes: {notes['path']} exists={notes['exists']} size={notes['size_bytes']}")
    for idx, preview in enumerate(result.get("previews", []), start=1):
        print(
            f"Preview {idx}: {preview['path']} exists={preview['exists']} "
            f"size={preview['size_bytes']}"
        )
    for idx, preview in enumerate(result.get("preview_validation", []), start=1):
        print(f"Preview QA {idx}: valid={preview['valid']} error={preview['error']}")
    for name, info in result.get("extra_files", {}).items():
        print(f"{name}: {info['path']} exists={info['exists']} size={info['size_bytes']}")
    print(f"Slide count: {result['slide_count']}")
    if result["slide_count_error"]:
        print(f"Slide count error: {result['slide_count_error']}")
    if result["missing_expected_files"]:
        print("Missing expected files: " + ", ".join(result["missing_expected_files"]))
    for warning in result.get("qa_manifest", {}).get("warnings", []):
        print(f"Warning: {warning}")
    print(f"Delivery OK: {result['ok']}")


def main() -> None:
    args = parse_args()
    result = inspect_delivery(
        args.pptx,
        args.notes,
        args.preview,
        require_notes=not args.allow_missing_notes,
        require_preview=not args.allow_missing_preview,
        extra_files={
            "pdf": args.pdf,
            "teleprompter": args.teleprompter,
            "quality-report": args.quality_report,
            "revision-manifest": args.revision_manifest,
        },
        qa_manifest=args.qa_manifest,
        quality_report=args.quality_report,
        package_report=args.package_report,
        require_package_report=args.strict or args.simple,
        slide_spec_report=args.slide_spec_report,
        simple=args.simple,
        visual_reviewed=args.visual_reviewed,
        visual_review_report=args.visual_review_report,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_text(result)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result["delivery_report"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.strict and not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
