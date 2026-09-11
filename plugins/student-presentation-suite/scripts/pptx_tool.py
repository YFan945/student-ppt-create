#!/usr/bin/env python3
"""Stable PPTX-only command facade for the suite-owned presentation runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.pptx_runtime import (  # noqa: E402
    add_slide,
    apply_cjk_fonts,
    clean_package,
    compare_baseline,
    delete_slide,
    fetch_images,
    pack_directory,
    parse_font_map,
    record_baseline,
    reorder_slides,
    safe_extract_package,
    validate_pptx,
)
from shared.pptx_runtime.normalize import normalize_generated_package  # noqa: E402
from shared.pptx_runtime.package import count_registered_slides  # noqa: E402
from shared.pptx_runtime.render import align_rendered_pages, render_pptx  # noqa: E402
from shared.pptx_runtime.thumbnail import (  # noqa: E402
    create_thumbnail_grids,
    slide_metadata,
    slide_text_content,
)
from shared.slide_spec_contract import load_slide_spec, validate_slide_spec  # noqa: E402

PPTX_SUFFIXES = {".pptx", ".potx"}
ASSET_MANIFEST_SCHEMA = ROOT / "references" / "asset-manifest.schema.json"
# 文本抽取子进程的超时：markitdown 曾是全仓唯一没有 timeout 的执行点。
TEXT_EXTRACTION_TIMEOUT_SEC = 180
# 允许作为 add-slide 来源的部件名（禁止目录分隔符与路径穿越）
_SLIDE_PART_NAME_RE = re.compile(r"^slide(Layout|Master)?\d+\.xml$")


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _existing_file(value: str) -> Path:
    path = _path(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"file does not exist: {path}")
    return path


def _pptx_file(value: str) -> Path:
    path = _existing_file(value)
    if path.suffix.casefold() not in PPTX_SUFFIXES:
        raise argparse.ArgumentTypeError(f"expected .pptx or .potx: {path}")
    return path


def _directory(value: str) -> Path:
    path = _path(value)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f"directory does not exist: {path}")
    return path


def _basename(value: str) -> str:
    if not value or Path(value).name != value or value in {".", ".."}:
        raise argparse.ArgumentTypeError(
            "expected a filename prefix without directory components"
        )
    return value


def _slide_part_name(value: str) -> str:
    """只接受包内的幻灯片部件名。

    ``edit.add_slide`` 内部执行 ``slides / source``；若传入绝对路径，
    ``Path`` 会整体覆盖为绝对路径，任意可读文件都会被复制进 PPTX。
    """
    name = Path(str(value)).name
    if not _SLIDE_PART_NAME_RE.match(name):
        raise argparse.ArgumentTypeError(
            f"expected a slide part name like slide2.xml, got {value!r}"
        )
    return name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slide_count(path: Path) -> int:
    """按 presentation.xml sldIdLst 的注册页数计数（与 render 的 slide_metadata 口径一致）。"""
    return count_registered_slides(path) or 0


def _ensure_separate_output(source: Path, output: Path) -> None:
    if source.resolve() == output.resolve():
        raise SystemExit("refusing to overwrite the source package; choose a different --output")
    output.parent.mkdir(parents=True, exist_ok=True)


def _write_ooxml_text_fallback(path: Path, output: Path) -> None:
    lines = ["# PPTX text extraction", ""]
    for slide in slide_text_content(path):
        lines.extend(
            [
                f"## Slide {slide['index']}: {slide.get('title') or '(untitled)'}",
                "",
                str(slide.get("text") or ""),
                "",
            ]
        )
    output.write_text("\n".join(lines), encoding="utf-8")


def command_inspect(args: argparse.Namespace) -> int:
    path: Path = args.input
    try:
        slide_count = _slide_count(path)
    except (OSError, zipfile.BadZipFile) as exc:
        print(
            json.dumps(
                {"ok": False, "path": str(path), "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    try:
        slides = slide_metadata(path)
        metadata_error = None
    except Exception as exc:  # inspect remains usable for damaged packages; validate reports blockers
        slides = []
        metadata_error = str(exc)
    result: dict[str, Any] = {
        "ok": metadata_error is None,
        "path": str(path),
        "sha256": _sha256(path),
        "slide_count": slide_count,
        "metadata_version": 1,
        "slides": slides,
        "size_bytes": path.stat().st_size,
    }
    if metadata_error:
        result["metadata_warning"] = metadata_error
    if args.text_output:
        output: Path = args.text_output
        output.parent.mkdir(parents=True, exist_ok=True)
        command = shutil.which("markitdown")
        if not command:
            _write_ooxml_text_fallback(path, output)
            result["text_output"] = str(output)
            result["text_extraction"] = "suite-ooxml-fallback"
            result["text_extraction_warning"] = "markitdown is unavailable"
        else:
            try:
                completed = subprocess.run(
                    [command, str(path), "-o", str(output)],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    # 全仓唯一缺 timeout 的执行点：超大/异常 PPTX 会让门禁永久挂死。
                    timeout=TEXT_EXTRACTION_TIMEOUT_SEC,
                )
            except subprocess.TimeoutExpired:
                # 超时就退回套件自带的 OOXML 抽取，保证流程不会卡住。
                _write_ooxml_text_fallback(path, output)
                result["text_output"] = str(output)
                result["text_extraction"] = "suite-ooxml-fallback"
                result["text_extraction_warning"] = (
                    f"markitdown timed out after {TEXT_EXTRACTION_TIMEOUT_SEC}s"
                )
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["ok"] else 1
            result["text_output"] = str(output)
            result["text_extraction_returncode"] = completed.returncode
            if completed.returncode != 0:
                _write_ooxml_text_fallback(path, output)
                result["text_extraction"] = "suite-ooxml-fallback"
                result["text_extraction_warning"] = completed.stderr.strip()
            else:
                result["text_extraction"] = "markitdown"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def command_unpack(args: argparse.Namespace) -> int:
    source: Path = args.input
    output: Path = args.output
    output_existed = output.exists()
    if output_existed and not output.is_dir():
        raise SystemExit(f"output path must be a directory: {output}")
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"output directory must be absent or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    try:
        safe_extract_package(source, output)
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        if output_existed:
            output.mkdir(parents=True, exist_ok=True)
        raise
    print(json.dumps({"ok": True, "input": str(source), "output": str(output)}))
    return 0


def command_pack(args: argparse.Namespace) -> int:
    source: Path = args.input
    output: Path = args.output
    if output.suffix.casefold() not in PPTX_SUFFIXES:
        raise SystemExit("pack --output must end in .pptx or .potx")
    if output.is_relative_to(source):
        raise SystemExit("pack output must be outside the unpacked input directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    pack_directory(source, output)
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(source),
                "output": str(output),
                "sha256": _sha256(output),
                "slide_count": _slide_count(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_add_slide(args: argparse.Namespace) -> int:
    target: Path = args.input
    if target.is_file():
        output: Path = args.output
        if output.suffix.casefold() not in PPTX_SUFFIXES:
            raise SystemExit("add-slide --output must end in .pptx or .potx")
        _ensure_separate_output(target, output)
        with tempfile.TemporaryDirectory(prefix="pptx-edit-") as tmp:
            unpacked = Path(tmp)
            safe_extract_package(target, unpacked)
            created = add_slide(unpacked, args.source, args.after)
            pack_directory(unpacked, output)
    else:
        if args.output:
            raise SystemExit("--output is not accepted for an unpacked directory")
        created = add_slide(target, args.source, args.after)
    print(json.dumps({"ok": True, "created_slide": created}, ensure_ascii=False))
    return 0


def _package_edit_paths(target: Path, output: Path | None) -> tuple[Path, Path]:
    if output is None:
        raise SystemExit("--output is required for package input to protect the source")
    if output.suffix.casefold() not in PPTX_SUFFIXES:
        raise SystemExit("--output must end in .pptx or .potx")
    _ensure_separate_output(target, output)
    return target, output


def command_delete_slide(args: argparse.Namespace) -> int:
    target: Path = args.input
    if target.is_file():
        source, output = _package_edit_paths(target, args.output)
        with tempfile.TemporaryDirectory(prefix="pptx-edit-") as tmp:
            unpacked = Path(tmp)
            safe_extract_package(source, unpacked)
            delete_slide(unpacked, args.slide)
            clean_package(unpacked)
            pack_directory(unpacked, output)
    else:
        if args.output:
            raise SystemExit("--output is not accepted for an unpacked directory")
        delete_slide(target, args.slide)
    print(json.dumps({"ok": True, "deleted_slide": args.slide}, ensure_ascii=False))
    return 0


def command_reorder_slides(args: argparse.Namespace) -> int:
    target: Path = args.input
    if target.is_file():
        source, output = _package_edit_paths(target, args.output)
        with tempfile.TemporaryDirectory(prefix="pptx-edit-") as tmp:
            unpacked = Path(tmp)
            safe_extract_package(source, unpacked)
            reorder_slides(unpacked, args.slides)
            pack_directory(unpacked, output)
    else:
        if args.output:
            raise SystemExit("--output is not accepted for an unpacked directory")
        reorder_slides(target, args.slides)
    print(json.dumps({"ok": True, "slide_order": args.slides}, ensure_ascii=False))
    return 0


def command_clean(args: argparse.Namespace) -> int:
    try:
        removed = clean_package(args.input)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "removed": removed}, ensure_ascii=False, indent=2))
    return 0


def command_cjk_fonts(args: argparse.Namespace) -> int:
    try:
        mapping = parse_font_map(list(args.map))
        total = apply_cjk_fonts(args.input, mapping, args.output)
    except (ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {"ok": True, "pptx": str(args.input), "mapping": mapping, "ea_written": total},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0




def command_fetch_images(args: argparse.Namespace) -> int:
    try:
        report = fetch_images(args.sources, args.query, args.out_dir, args.timeout)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    report_path = args.out_dir / "fetch-images-report.json"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "report": str(report_path)}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1




def command_visual_baseline(args: argparse.Namespace) -> int:
    if args.action == "record":
        payload = record_baseline(args.render_dir, args.baseline)
        print(json.dumps({"ok": True, "action": "record", "pages": payload["pages"],
                          "baseline": str(args.baseline)}, ensure_ascii=False))
        return 0
    report = compare_baseline(args.render_dir, args.baseline, args.threshold)
    report["action"] = "compare"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def command_validate(args: argparse.Namespace) -> int:
    path: Path = args.input
    original: Path | None = args.original
    if not path.is_file():
        print(json.dumps({"ok": False, "findings": [{"code": "input", "part": str(path), "severity": "error", "detail": "validate requires a packed PPTX"}]}))
        return 1
    if original is not None and original.resolve() == path.resolve():
        raise SystemExit("--original 与输入为同一文件；差分去重会把全部 findings 误删，请提供原始源包")
    result = {
        **validate_pptx(path, original),
        "input": str(path),
        "pptx_sha256": _sha256(path) if path.is_file() else None,
        "original": str(original) if original else None,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for finding in result["findings"]:
            print(
                f"[{finding['severity']}] {finding['code']}: "
                f"{finding['part']}: {finding['detail']}"
            )
    return 0 if result["ok"] else 1


def command_normalize_generated(args: argparse.Namespace) -> int:
    try:
        changed = normalize_generated_package(args.input, args.output)
    except FileExistsError as exc:
        raise SystemExit(f"输出已存在，拒绝覆盖: {exc}") from exc
    except (OSError, ValueError) as exc:
        raise SystemExit(f"归一化失败: {exc}") from exc
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(args.input.resolve()),
                "output": str(args.output.resolve()),
                "changed": changed,
            },
            ensure_ascii=False,
        )
    )
    return 0


def command_thumbnail(args: argparse.Namespace) -> int:
    result = create_thumbnail_grids(
        args.input,
        args.output_prefix,
        args.cols,
        args.rows,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "metadata_version": result["metadata_version"],
                "outputs": [str(path) for path in result["outputs"]],
                "slides": result["slides"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_render(args: argparse.Namespace) -> int:
    source: Path = args.input
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        pdf, pages, messages = render_pptx(
            source, output_dir, args.prefix, args.format, args.dpi
        )
    except (FileNotFoundError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "stage": "render", "error": str(exc)}, ensure_ascii=False))
        return 1
    try:
        metadata = slide_metadata(source)
    except Exception as exc:  # 半损坏包：转成干净错误而非 traceback
        print(json.dumps({"ok": False, "stage": "metadata", "error": str(exc)}, ensure_ascii=False))
        return 1
    try:
        pages, hidden_placeholders = align_rendered_pages(
            pages, metadata, output_dir, args.prefix, args.format
        )
    except ValueError as exc:
        print(json.dumps({"ok": False, "stage": "render", "error": str(exc)}, ensure_ascii=False))
        return 1
    ok = len(pages) == len(metadata)
    print(
        json.dumps(
            {
                "ok": ok,
                "pptx": str(source),
                "pdf": str(pdf),
                "pages": [str(page) for page in pages],
                "slide_count": len(metadata),
                "rendered_page_count": len(pages),
                "hidden_placeholders": hidden_placeholders,
                "messages": [message for message in messages if message],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


def _validate_package_report(report: Path, pptx: Path) -> dict:
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read package report: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("package report root must be an object")
    if data.get("pptx_sha256") != _sha256(pptx):
        raise SystemExit("package report does not match the current PPTX")
    if data.get("ok") is not True:
        raise SystemExit("package report did not pass validation")
    if data.get("validation_profile") != "openxml-sdk-plus-suite-semantic-v4":
        raise SystemExit("package report must use the complete suite validation profile")
    schema = data.get("schema_validation") or {}
    if schema.get("performed") is not True:
        raise SystemExit("package report schema validation was not performed")
    if (schema.get("error_count") or 0) != 0:
        raise SystemExit("package report contains Open XML schema errors")
    return data


PLACEHOLDER_PATTERN = re.compile(
    r"\b(?:lorem ipsum|todo|tbd|placeholder|insert (?:text|image|chart))\b|"
    r"(?:待补充|占位符|在此输入|插入(?:图片|图表|文字))",
    re.IGNORECASE,
)


def command_content_qa(args: argparse.Namespace) -> int:
    pptx: Path = args.pptx
    try:
        spec = load_slide_spec(args.slide_spec)
        extracted = slide_text_content(pptx)
        metadata = slide_metadata(pptx)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"cannot perform content QA: {exc}") from exc
    expected = spec.get("slides") or []
    findings: list[dict[str, Any]] = []
    if len(extracted) != len(expected):
        findings.append({"severity": "blocker", "code": "slide-count", "detail": f"PPTX has {len(extracted)} slides; Slide Spec has {len(expected)}"})
    for index, (actual, planned) in enumerate(zip(extracted, expected, strict=False), 1):
        text = str(actual.get("text") or "")
        title = str(planned.get("title") or "").strip()
        normalized_title = re.sub(r"\s+", "", title).casefold()
        normalized_text = re.sub(r"\s+", "", text).casefold()
        if not text.strip():
            findings.append({"slide": index, "severity": "blocker", "code": "empty-slide", "detail": "slide has no extractable content"})
        if title and normalized_title not in normalized_text:
            findings.append({"slide": index, "severity": "blocker", "code": "title-drift", "detail": "planned title is not present in the generated slide"})
        if PLACEHOLDER_PATTERN.search(text):
            findings.append({"slide": index, "severity": "blocker", "code": "placeholder", "detail": "placeholder text remains"})
        if planned.get("speaker_notes") and index <= len(metadata) and not metadata[index - 1].get("has_notes"):
            findings.append({"slide": index, "severity": "blocker", "code": "missing-notes", "detail": "Slide Spec requires speaker notes but the PPTX slide has no notes part"})
        # id 可能不是数字（手写 spec），旧实现在 try 块外直接 int() 会抛未捕获 ValueError。
        planned_id = planned.get("id", index)
        try:
            ordered = int(planned_id) == index
        except (TypeError, ValueError):
            ordered = False
        if not ordered:
            findings.append({"slide": index, "severity": "blocker", "code": "page-order", "detail": f"Slide Spec id {planned_id!r} is not in rendered page order"})
    blockers = [item for item in findings if item["severity"] == "blocker"]
    payload = {
        "ok": not blockers,
        "report_type": "content-qa-v1",
        "pptx": str(pptx),
        "pptx_sha256": _sha256(pptx),
        "slide_spec": str(args.slide_spec),
        "slide_spec_sha256": _sha256(args.slide_spec),
        "slide_count": len(extracted),
        "findings": findings,
        "blocker_count": len(blockers),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": payload["ok"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if payload["ok"] else 1


def command_validate_asset_manifest(args: argparse.Namespace) -> int:
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        schema = json.loads(ASSET_MANIFEST_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read asset manifest or schema: {exc}") from exc
    errors = [
        {"path": "/".join(str(part) for part in error.absolute_path), "message": error.message}
        for error in Draft202012Validator(schema).iter_errors(data)
    ]
    if not errors:
        for index, asset in enumerate(data.get("assets", [])):
            path_value = asset.get("path")
            if path_value and not Path(path_value).expanduser().is_file():
                errors.append({"path": f"assets/{index}/path", "message": "asset file does not exist"})
            if path_value and (not asset.get("width") or not asset.get("height")):
                errors.append({"path": f"assets/{index}", "message": "file assets require width and height"})
    payload = {"ok": not errors, "report_type": "asset-manifest-validation-v1", "manifest": str(args.manifest), "manifest_sha256": _sha256(args.manifest), "errors": errors}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def command_visual_inspection(args: argparse.Namespace) -> int:
    pptx: Path = args.pptx
    previews: list[Path] = args.preview
    slide_count = _slide_count(pptx)
    if len(previews) != slide_count:
        raise SystemExit(f"visual inspection requires exactly {slide_count} previews")
    if args.repair_cycle not in {0, 1}:
        raise SystemExit("--repair-cycle must be 0 or 1")
    try:
        review = json.loads(args.findings.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read visual findings: {exc}") from exc
    pages = review.get("pages") if isinstance(review, dict) else None
    if not isinstance(pages, list) or len(pages) != slide_count:
        raise SystemExit("visual findings must contain one pages entry per slide")
    normalized_pages = []
    for index, (page, preview) in enumerate(zip(pages, previews, strict=True), 1):
        if not isinstance(page, dict) or page.get("slide") != index:
            raise SystemExit(f"visual findings page {index} has an invalid slide number")
        if page.get("checked") is not True:
            raise SystemExit(f"visual findings page {index} was not explicitly checked")
        blockers = page.get("blockers") or []
        warnings = page.get("warnings") or []
        if not isinstance(blockers, list) or not isinstance(warnings, list):
            raise SystemExit(f"visual findings page {index} blockers/warnings must be arrays")
        normalized_pages.append({
            "slide": index,
            "checked": True,
            "preview": str(preview),
            "preview_sha256": _sha256(preview),
            "blockers": blockers,
            "warnings": warnings,
            "notes": str(page.get("notes") or ""),
        })
    blocker_count = sum(len(page["blockers"]) for page in normalized_pages)
    payload = {
        "ok": blocker_count == 0,
        "report_type": "visual-inspection-v1",
        "pptx": str(pptx),
        "pptx_sha256": _sha256(pptx),
        "slide_count": slide_count,
        "repair_cycle": args.repair_cycle,
        "checked_page_count": slide_count,
        "blocker_count": blocker_count,
        "pages": normalized_pages,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": payload["ok"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if payload["ok"] else 1


def _validate_bound_qa_report(report: Path, pptx: Path, report_type: str) -> dict[str, Any]:
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {report_type} report: {exc}") from exc
    if not isinstance(data, dict) or data.get("report_type") != report_type:
        raise SystemExit(f"invalid {report_type} report")
    if data.get("pptx_sha256") != _sha256(pptx):
        raise SystemExit(f"{report_type} report does not match the current PPTX")
    if data.get("ok") is not True or int(data.get("blocker_count", 0)) != 0:
        raise SystemExit(f"{report_type} report contains blockers")
    return data


def command_qa_manifest(args: argparse.Namespace) -> int:
    pptx: Path = args.pptx
    previews: list[Path] = args.preview
    slide_count = _slide_count(pptx)
    if previews and len(previews) != slide_count:
        raise SystemExit(
            f"preview count ({len(previews)}) must equal slide count ({slide_count}) "
            "when previews are provided"
        )
    package_report_data = None
    if args.package_report:
        package_report_data = _validate_package_report(args.package_report, pptx)
    content_qa_data = None
    visual_inspection_data = None
    if args.content_qa:
        content_qa_data = _validate_bound_qa_report(args.content_qa, pptx, "content-qa-v1")
    if previews:
        if not args.content_qa or not args.visual_inspection or not args.asset_manifest or not args.asset_manifest_report:
            raise SystemExit("rendered QA requires content, visual inspection, and asset manifest evidence")
        try:
            asset_report_data = json.loads(args.asset_manifest_report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"cannot read asset manifest report: {exc}") from exc
        if asset_report_data.get("ok") is not True or asset_report_data.get("manifest_sha256") != _sha256(args.asset_manifest):
            raise SystemExit("asset manifest report does not bind a valid current manifest")
        visual_inspection_data = _validate_bound_qa_report(args.visual_inspection, pptx, "visual-inspection-v1")
        if visual_inspection_data.get("checked_page_count") != slide_count:
            raise SystemExit("visual inspection does not cover every slide")
        bound_hashes = [page.get("preview_sha256") for page in visual_inspection_data.get("pages", [])]
        if bound_hashes != [_sha256(path) for path in previews]:
            raise SystemExit("visual inspection preview hashes do not match --preview files")
    try:
        spec_report_data = json.loads(args.slide_spec_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read Slide Spec report: {exc}") from exc
    if not isinstance(spec_report_data, dict) or spec_report_data.get("valid") is not True:
        raise SystemExit("Slide Spec validation report did not pass")
    # spec 自规划期未被改动时不再重复校验（规划期已由 validate_slide_spec.py 校验），
    # QA 只做 hash 绑定与页数核对，避免门禁叠罗汉。spec 被改动时才重校验以捕获漂移。
    spec_hash = spec_report_data.get("slide_spec_sha256")
    actual_spec_hash = _sha256(args.slide_spec)
    try:
        if actual_spec_hash == spec_hash:
            spec_data, spec_errors = load_slide_spec(args.slide_spec), []
        else:
            spec_data, spec_errors, actual_spec_hash = validate_slide_spec(args.slide_spec)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot validate Slide Spec: {exc}") from exc
    if spec_errors:
        raise SystemExit(
            "Slide Spec no longer passes validation: "
            + "; ".join(error["message"] for error in spec_errors[:3])
        )
    if not spec_hash or actual_spec_hash != spec_hash:
        raise SystemExit("Slide Spec report does not bind the current spec")
    if len((spec_data or {}).get("slides") or []) != slide_count:
        raise SystemExit("Slide Spec slide count does not match the current PPTX")
    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    # scenario_contract_passed 恒为 True：由上方对 Slide Spec 的重校验推导
    # （spec 有效且页数与 slide_count 一致），并非独立的场景检测结果。
    payload = {
        "pptx_sha256": _sha256(pptx),
        "slide_count": slide_count,
        # 未提供 --preview 时如实记 null（"未渲染"），与"渲染了 0 页"区分开；
        # 下游 delivery_check 对 None/0 均按未渲染处理。
        "rendered_page_count": len(previews) if previews else None,
        "scenario_contract_passed": True,
        "slide_spec": str(args.slide_spec),
        "slide_spec_report": str(args.slide_spec_report),
        "slide_spec_report_sha256": _sha256(args.slide_spec_report),
        "slide_spec_sha256": spec_hash,
        "preview_files": [str(path) for path in previews],
        "preview_sha256": [_sha256(path) for path in previews],
    }
    if previews:
        payload["visual_inspection"] = {
            "completed": True,
            "inspected_pages": list(range(1, slide_count + 1)),
            "repair_cycles": visual_inspection_data["repair_cycle"],
            "remaining_blockers": 0,
        }
        payload["visual_inspection_report"] = str(args.visual_inspection)
        payload["visual_inspection_report_sha256"] = _sha256(args.visual_inspection)
        payload["asset_manifest"] = str(args.asset_manifest)
        payload["asset_manifest_sha256"] = _sha256(args.asset_manifest)
        payload["asset_manifest_report"] = str(args.asset_manifest_report)
        payload["asset_manifest_report_sha256"] = _sha256(args.asset_manifest_report)
    if content_qa_data is not None:
        payload["content_qa_report"] = str(args.content_qa)
        payload["content_qa_report_sha256"] = _sha256(args.content_qa)
    if package_report_data is not None:
        payload["package_report"] = str(args.package_report)
        payload["package_report_sha256"] = _sha256(args.package_report)
        payload["package_validation_profile"] = package_report_data.get(
            "validation_profile"
        )
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output)}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Suite-owned PPTX runtime facade")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="inspect a PPTX without modifying it")
    inspect.add_argument("input", type=_pptx_file)
    inspect.add_argument("--text-output", type=_path)
    inspect.set_defaults(handler=command_inspect)

    unpack = sub.add_parser("unpack", help="safely unpack a PPTX")
    unpack.add_argument("input", type=_pptx_file)
    unpack.add_argument("--output", required=True, type=_path)
    unpack.set_defaults(handler=command_unpack)

    pack = sub.add_parser("pack", help="pack an unpacked PPTX directory")
    pack.add_argument("input", type=_directory)
    pack.add_argument("--output", required=True, type=_path)
    pack.set_defaults(handler=command_pack)

    add_slide_parser = sub.add_parser("add-slide", help="add a slide without overwriting a package")
    add_slide_parser.add_argument("input", type=_path)
    # 必须校验：edit.py 内部做 `slides / source`，未净化的绝对路径会让
    # 任意可读文件被复制进 PPTX（旧实现这里没有任何 type 校验器）。
    add_slide_parser.add_argument("source", type=_slide_part_name)
    add_slide_parser.add_argument("--after")
    add_slide_parser.add_argument("--output", type=_path)
    add_slide_parser.set_defaults(handler=command_add_slide)

    delete_slide_parser = sub.add_parser(
        "delete-slide", help="delete a registered slide without overwriting a package"
    )
    delete_slide_parser.add_argument("input", type=_path)
    delete_slide_parser.add_argument("slide")
    delete_slide_parser.add_argument("--output", type=_path)
    delete_slide_parser.set_defaults(handler=command_delete_slide)

    reorder_parser = sub.add_parser(
        "reorder-slides", help="replace the complete slide order without overwriting a package"
    )
    reorder_parser.add_argument("input", type=_path)
    reorder_parser.add_argument("slides", nargs="+")
    reorder_parser.add_argument("--output", type=_path)
    reorder_parser.set_defaults(handler=command_reorder_slides)

    clean = sub.add_parser("clean", help="clean unreferenced parts from an unpacked package")
    clean.add_argument("input", type=_directory)
    clean.set_defaults(handler=command_clean)

    validate = sub.add_parser("validate", help="validate PPTX package and presentation XML")
    validate.add_argument("input", type=_path)
    validate.add_argument("--original", type=_pptx_file)
    validate.add_argument("--json", action="store_true")
    validate.add_argument("--output", type=_path)
    validate.set_defaults(handler=command_validate)
    cjk = sub.add_parser(
        "cjk-fonts",
        help="add <a:ea> East Asian typefaces for mapped latin fonts (CJK typography)",
    )
    cjk.add_argument("input", type=Path, help="generated PPTX to rewrite in place")
    cjk.add_argument(
        "--map",
        action="append",
        required=True,
        help="Latin=CJK pair, e.g. Cambria=SimHei; repeat for title/body fonts",
    )
    cjk.add_argument("--output", type=Path, default=None, help="write to a new file instead of in place")
    cjk.set_defaults(handler=command_cjk_fonts)
    fetch = sub.add_parser(
        "fetch-images",
        help="execute image providers from an image-sources.json contract",
    )
    fetch.add_argument("--sources", type=Path, required=True, help="path to image-sources.json")
    fetch.add_argument("--query", action="append", required=True, help="image query; repeat for multiple")
    fetch.add_argument("--out-dir", type=Path, required=True, help="directory for fetched assets")
    fetch.add_argument("--timeout", type=int, default=120, help="per-command timeout in seconds")
    fetch.set_defaults(handler=command_fetch_images)
    baseline = sub.add_parser(
        "visual-baseline",
        help="record or compare a perceptual-hash baseline of rendered pages",
    )
    baseline.add_argument("action", choices=("record", "compare"))
    baseline.add_argument("--render-dir", type=Path, required=True, help="directory of rendered PNGs")
    baseline.add_argument("--baseline", type=Path, required=True, help="baseline JSON path")
    baseline.add_argument("--threshold", type=int, default=6, help="max allowed bits distance (0-64)")
    baseline.set_defaults(handler=command_visual_baseline)




    normalize_generated = sub.add_parser(
        "normalize-generated",
        help="normalize a newly generated package to a distinct non-existing output",
    )
    normalize_generated.add_argument("input", type=_pptx_file)
    normalize_generated.add_argument("--output", required=True, type=_path)
    normalize_generated.set_defaults(handler=command_normalize_generated)

    thumbnail = sub.add_parser("thumbnail", help="create labeled template thumbnail grids")
    thumbnail.add_argument("input", type=_pptx_file)
    thumbnail.add_argument("--output-prefix", required=True, type=_path)
    thumbnail.add_argument("--cols", type=int, default=3)
    thumbnail.add_argument("--rows", type=int, default=4)
    thumbnail.set_defaults(handler=command_thumbnail)

    render = sub.add_parser("render", help="render every slide through LibreOffice and Poppler")
    render.add_argument("input", type=_pptx_file)
    render.add_argument("--output-dir", required=True, type=_path)
    render.add_argument("--prefix", required=True, type=_basename)
    render.add_argument("--format", choices=("jpg", "png"), default="png")
    render.add_argument("--dpi", type=int, default=150)
    render.set_defaults(handler=command_render)

    content_qa = sub.add_parser("content-qa", help="compare complete PPTX text and notes with the Slide Spec")
    content_qa.add_argument("--pptx", required=True, type=_pptx_file)
    content_qa.add_argument("--slide-spec", required=True, type=_existing_file)
    content_qa.add_argument("--output", required=True, type=_path)
    content_qa.set_defaults(handler=command_content_qa)

    asset_manifest = sub.add_parser("validate-asset-manifest", help="validate source, permission, dimensions, alt text, and fallback records")
    asset_manifest.add_argument("manifest", type=_existing_file)
    asset_manifest.add_argument("--output", type=_path)
    asset_manifest.set_defaults(handler=command_validate_asset_manifest)

    visual_inspection = sub.add_parser("visual-inspection", help="bind explicit page-by-page findings to rendered previews")
    visual_inspection.add_argument("--pptx", required=True, type=_pptx_file)
    visual_inspection.add_argument("--preview", action="append", required=True, type=_existing_file)
    visual_inspection.add_argument("--findings", required=True, type=_existing_file)
    visual_inspection.add_argument("--repair-cycle", type=int, default=0)
    visual_inspection.add_argument("--output", required=True, type=_path)
    visual_inspection.set_defaults(handler=command_visual_inspection)

    manifest = sub.add_parser("qa-manifest", help="bind inspected previews to the final PPTX")
    manifest.add_argument("--pptx", required=True, type=_pptx_file)
    manifest.add_argument("--preview", action="append", default=[], type=_existing_file)
    manifest.add_argument("--output", required=True, type=_path)
    manifest.add_argument(
        "--package-report",
        type=_existing_file,
        help="validate-produced package report to bind to the PPTX (optional)",
    )
    manifest.add_argument("--repair-cycles", type=int, default=0)
    manifest.add_argument("--no-repair-needed-reason")
    manifest.add_argument("--remaining-blockers", type=int, default=0)
    manifest.add_argument("--slide-spec-report", required=True, type=_existing_file)
    manifest.add_argument("--slide-spec", required=True, type=_existing_file)
    manifest.add_argument("--content-qa", type=_existing_file)
    manifest.add_argument("--visual-inspection", type=_existing_file)
    manifest.add_argument("--asset-manifest", type=_existing_file)
    manifest.add_argument("--asset-manifest-report", type=_existing_file)
    manifest.set_defaults(handler=command_qa_manifest)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command in {"add-slide", "delete-slide", "reorder-slides"}:
        target: Path = args.input
        if not target.exists() or (
            not target.is_dir() and target.suffix.casefold() not in PPTX_SUFFIXES
        ):
            raise SystemExit(f"expected unpacked directory or .pptx/.potx: {target}")
        if target.is_file() and args.output is None:
            raise SystemExit("--output is required for package input to protect the source")
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()
