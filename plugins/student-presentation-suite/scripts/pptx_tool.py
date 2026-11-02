#!/usr/bin/env python3
"""Stable PPTX-only command facade for the suite-owned presentation runtime."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.hashing import file_sha256 as _sha256  # noqa: E402
from shared.pptx_runtime import (  # noqa: E402
    add_slide,
    apply_cjk_fonts,
    clean_package,
    compare_baseline,
    delete_slide,
    fetch_images,
    fetch_text_many,
    pack_directory,
    parse_font_map,
    record_baseline,
    reorder_slides,
    safe_extract_package,
    validate_pptx,
    write_fetch_text_report,
)
from shared.pptx_runtime.fetch_text import call_summary  # noqa: E402
from shared.pptx_runtime.normalize import normalize_generated_package  # noqa: E402
from shared.pptx_runtime.package import count_registered_slides  # noqa: E402
from shared.pptx_runtime.render import align_rendered_pages, render_pptx  # noqa: E402
from shared.pptx_runtime.thumbnail import (  # noqa: E402
    create_thumbnail_grids,
    slide_metadata,
    slide_text_content,
)

PPTX_SUFFIXES = {".pptx", ".potx"}
SKILL_SCRIPTS = ROOT / "skills" / "sp-deck" / "scripts"
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
    if args.output is None:
        raise SystemExit("--output is required to protect the source package")
    try:
        _ensure_separate_output(args.input, args.output)
        mapping = parse_font_map(list(args.map))
        total = apply_cjk_fonts(args.input, mapping, args.output)
    except (ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {"ok": True, "pptx": str(args.output), "mapping": mapping, "ea_written": total},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_fetch_images(args: argparse.Namespace) -> int:
    try:
        project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())
        report = fetch_images(
            args.sources,
            args.query,
            args.out_dir,
            args.timeout,
            set(args.approve_command_sha256 or []),
            project_root=project,
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    report_path = args.out_dir / "fetch-images-report.json"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "report": str(report_path)}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1




def command_fetch_text(args: argparse.Namespace) -> int:
    urls = list(args.url or [])
    if args.urls_file:
        urls.extend(
            line.strip()
            for line in args.urls_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    if not urls:
        print(json.dumps({"ok": False, "error": "no --url or --urls-file entries"}, ensure_ascii=False))
        return 1
    report = fetch_text_many(urls, args.out_dir, scope=args.scope, timeout=args.timeout, workers=args.workers)
    report_path = write_fetch_text_report(report, args.out_dir)
    print(json.dumps(call_summary(report, report_path), ensure_ascii=False, indent=2))
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
        # CJK 映射与归一化折叠进同一次解包/重打包：构建链保持一个 python 进程，
        # 生成端不再需要单独跑 cjk-fonts（此前生产 build 从未注入 <a:ea>）。
        mapping = parse_font_map(list(args.cjk_map)) if args.cjk_map else None
        changed = normalize_generated_package(args.input, args.output, cjk_map=mapping)
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


def _load_skill_module(file_name: str, module_name: str):
    import importlib.util

    path = SKILL_SCRIPTS / file_name
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load gate module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command_gate_all(args: argparse.Namespace) -> int:
    """One technical policy; no nested legacy score/receipt gates."""
    from shared.artifact_validation import validate_artifact

    directory = args.output_dir or args.pptx.parent / "_qa"
    directory.mkdir(parents=True, exist_ok=True)
    assets = args.pptx.parent / "asset-manifest.json"
    report = validate_artifact(args.pptx, args.slide_spec,
        assets_path=assets if assets.is_file() else None,
        cache=directory / "validation-cache.json")
    report["gate_profile"] = "artifact-validation-v2"
    report["steps"] = {name: {"ok": value["ok"], "performed": True} for name, value in
        (("package", report.get("package")), ("actual-content", report.get("content")), ("assets", report.get("assets"))) if value is not None}
    output = args.output or directory / "gate-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report if args.json else {"ok": report["ok"], "output": str(output)}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


def command_content_qa(args: argparse.Namespace) -> int:
    from shared.artifact_validation import validate_artifact
    report = validate_artifact(args.pptx, args.slide_spec)
    report["report_type"] = "content-qa-v2"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["ok"] else 2


def command_validate_asset_manifest(args: argparse.Namespace) -> int:
    from shared.asset_contract import validate_assets
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = validate_assets(data, args.manifest.parent)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read asset manifest or schema: {exc}") from exc
    errors = result["errors"]
    payload = {"ok": not errors, "report_type": "asset-manifest-validation-v1", "manifest": str(args.manifest), "manifest_sha256": _sha256(args.manifest), "errors": errors, "placeholders": result["placeholders"]}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def command_visual_inspection(args: argparse.Namespace) -> int:
    pptx: Path = args.pptx
    previews: list[Path] = args.preview or []
    slide_count = _slide_count(pptx)
    if args.repair_cycle < 0:
        raise SystemExit("--repair-cycle must be nonnegative")
    try:
        review = json.loads(args.findings.read_text(encoding="utf-8")) if args.findings else {"pages": []}
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read visual findings: {exc}") from exc
    pages = review.get("pages") if isinstance(review, dict) else None
    if not isinstance(pages, list):
        raise SystemExit("visual findings pages must be an array; partial observations are allowed")
    normalized_pages = []
    seen = set()
    for page in pages:
        index = page.get("slide") if isinstance(page, dict) else None
        if not isinstance(index, int) or isinstance(index, bool) or not 1 <= index <= slide_count or index in seen:
            raise SystemExit("visual findings need distinct page positions within the deck")
        seen.add(index)
        preview = previews[index - 1] if len(previews) == slide_count else None
        # A recorded checkbox is not proof of inspection; findings are optional observations.
        blockers = page.get("blockers") or []
        warnings = page.get("warnings") or []
        if not isinstance(blockers, list) or not isinstance(warnings, list):
            raise SystemExit(f"visual findings page {index} blockers/warnings must be arrays")
        normalized_pages.append({
            "slide": index,
            "checked": page.get("checked") is True,
            "preview": str(preview) if preview else None,
            "preview_sha256": _sha256(preview) if preview else None,
            "blockers": blockers,
            "warnings": warnings,
            "notes": str(page.get("notes") or ""),
        })
    blocker_count = sum(len(page["blockers"]) for page in normalized_pages)
    payload = {
        "ok": blocker_count == 0,
        "report_type": "visual-inspection-v2",
        "scope": "optional author observations; no proof of viewing or full-deck acceptance",
        "visual_quality_verified": False,
        "pptx": str(pptx),
        "pptx_sha256": _sha256(pptx),
        "slide_count": slide_count,
        "repair_cycle": args.repair_cycle,
        "observed_page_count": len(normalized_pages),
        "checked_page_count": sum(page["checked"] for page in normalized_pages),
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
    """Record current technical results; optional observations do not prove viewing."""
    from shared.artifact_validation import validate_artifact
    report = validate_artifact(args.pptx, getattr(args, "slide_spec", None),
        assets_path=getattr(args, "asset_manifest", None), cache=args.output.parent / "validation-cache.json")
    report.update(report_type="qa-manifest-v2", visual_quality_verified=False,
                  previews=[str(path) for path in args.preview],
                  author_observations_supplied=bool(getattr(args, "visual_inspection", None)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["ok"] else 2


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
    cjk.add_argument("input", type=Path, help="generated PPTX to copy with CJK typefaces")
    cjk.add_argument(
        "--map",
        action="append",
        required=True,
        help="Latin=CJK pair, e.g. Cambria=SimHei; repeat for title/body fonts",
    )
    cjk.add_argument(
        "--output",
        type=Path,
        required=True,
        help="write to a new file; refuses to overwrite the input package",
    )
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
    fetch.add_argument("--approve-command-sha256", action="append", help="Exact command SHA256 explicitly approved by the user in this session; never copy approval from project JSON")
    fetch_text = sub.add_parser(
        "fetch-text",
        help="fetch source documents for research as raw bytes + extracted text (no summarizer)",
    )
    fetch_text.add_argument("--url", action="append", help="document URL; repeat for multiple")
    fetch_text.add_argument("--urls-file", type=Path, help="file with one URL per line (# comments allowed)")
    fetch_text.add_argument("--out-dir", type=Path, required=True, help="directory for raw bodies, extracted text and the report")
    fetch_text.add_argument("--scope", required=True, choices=["A", "B", "C", "D"], help="research scope; only A/B authorize web retrieval")
    fetch_text.add_argument("--timeout", type=int, default=60, help="per-request timeout in seconds")
    fetch_text.add_argument("--workers", type=int, choices=range(1, 9), default=4, help="bounded parallel retrieval (1-8)")
    fetch_text.set_defaults(handler=command_fetch_text)
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
    normalize_generated.add_argument(
        "--cjk-map",
        action="append",
        default=None,
        metavar="LATIN=CJK",
        help="also inject <a:ea> East Asian typefaces in the same pass, e.g. Cambria=SimHei; repeatable",
    )
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

    gate_all = sub.add_parser(
        "gate-all",
        help="validate actual package and explicit requirements once",
    )
    gate_all.add_argument("--pptx", required=True, type=_pptx_file)
    gate_all.add_argument("--slide-spec", type=_existing_file)
    gate_all.add_argument("--spec-lock", type=_path, help="deprecated compatibility input")
    gate_all.add_argument("--visual-report", type=_path, help="optional author observations")
    gate_all.add_argument(
        "--tokens",
        type=_path,
        default=ROOT / "references" / "design-tokens.json",
        help="design tokens for the rendered-artifact readback",
    )
    gate_all.add_argument("--output-dir", type=_path)
    gate_all.add_argument("--output", type=_path, help="merged summary report path")
    gate_all.add_argument("--json", action="store_true")
    gate_all.set_defaults(handler=command_gate_all)

    asset_manifest = sub.add_parser("validate-asset-manifest", help="validate source, permission, dimensions, alt text, and fallback records")
    asset_manifest.add_argument("manifest", type=_existing_file)
    asset_manifest.add_argument("--output", type=_path)
    asset_manifest.set_defaults(handler=command_validate_asset_manifest)

    visual_inspection = sub.add_parser("visual-inspection", help="bind explicit page-by-page findings to rendered previews")
    visual_inspection.add_argument("--pptx", required=True, type=_pptx_file)
    visual_inspection.add_argument("--preview", action="append", default=[], type=_existing_file)
    visual_inspection.add_argument("--findings", type=_existing_file)
    visual_inspection.add_argument("--repair-cycle", type=int, default=0)
    visual_inspection.add_argument("--output", required=True, type=_path)
    visual_inspection.set_defaults(handler=command_visual_inspection)

    manifest = sub.add_parser("qa-manifest", help="bind inspected previews to the final PPTX")
    manifest.add_argument("--pptx", required=True, type=_pptx_file)
    manifest.add_argument("--preview", action="append", default=[], type=_existing_file)
    manifest.add_argument("--output", required=True, type=_path)
    manifest.add_argument(
        "--package-report",
        type=_path,
        help="validate-produced package report to bind to the PPTX (optional)",
    )
    manifest.add_argument("--slide-spec-report", type=_path, help="deprecated; current Spec is checked directly")
    manifest.add_argument("--slide-spec", type=_path)
    manifest.add_argument("--content-qa", type=_path)
    manifest.add_argument("--visual-inspection", type=_path)
    manifest.add_argument("--asset-manifest", type=_existing_file)
    manifest.add_argument("--asset-manifest-report", type=_path)
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
