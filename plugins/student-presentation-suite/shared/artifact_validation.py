"""One technical validation policy for production and all public gate routes."""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from shared.artifact_fingerprints import content_digest
from shared.asset_contract import validate_assets
from shared.hashing import file_sha256
from shared.slide_spec_contract import validate_slide_spec

ROOT = Path(__file__).resolve().parents[1]
POLICY_VERSION = "artifact-validation-v2"


def content_checker():
    directory = str(ROOT / "skills/sp-deck/scripts")
    if directory not in sys.path:
        sys.path.insert(0, directory)
    return importlib.import_module("pptx_actual_content_check")


def validation_key(pptx: Path, spec: Path | None = None, original: Path | None = None,
                   assets: Path | None = None) -> str:
    """Cache only unchanged technical inputs; never use it as proof of viewing."""
    inputs: list[Any] = [POLICY_VERSION, file_sha256(pptx), content_digest(ROOT / "package.json")]
    inputs.extend((str(path.resolve()), content_digest(path) if path.is_file() else "missing") if path else None
                  for path in (spec, original, assets))
    if assets and assets.is_file():
        try:
            for asset in json.loads(assets.read_text(encoding="utf-8")).get("assets", []):
                if asset.get("path"):
                    path = (assets.parent / asset["path"]).resolve()
                    inputs.append((str(path), file_sha256(path) if path.is_file() else None))
        except (ValueError, TypeError, AttributeError):
            pass  # Validation returns the malformed-input error.
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_artifact(pptx: Path, spec_path: Path | None = None, *, original: Path | None = None,
                      assets_path: Path | None = None, cache: Path | None = None) -> dict[str, Any]:
    from shared.pptx_runtime import validate_pptx

    if not pptx.is_file():
        return {"ok": False, "policy": POLICY_VERSION, "issues": [{"code": "pptx_missing", "severity": "critical", "path": str(pptx)}]}
    key = validation_key(pptx, spec_path, original, assets_path)
    if cache and cache.is_file():
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
            if saved.get("key") == key and isinstance(saved.get("report"), dict):
                return {**saved["report"], "reused": True}
        except (OSError, ValueError, AttributeError):
            pass
    try:
        package = validate_pptx(pptx, original)
    except (BadZipFile, ParseError, OSError, ValueError) as exc:
        package = {"ok": False, "issues": [{"code": "unreadable_package", "severity": "critical", "message": str(exc)}]}
    report: dict[str, Any] = {"ok": False, "policy": POLICY_VERSION, "key": key, "reused": False,
                              "package": package, "issues": [], "pptx_sha256": file_sha256(pptx)}
    spec: dict[str, Any] = {}
    if spec_path:
        if not spec_path.is_file():
            report["issues"].append({"code": "slide_spec_missing", "severity": "critical"})
        else:
            spec, errors, _ = validate_slide_spec(spec_path)
            report["issues"].extend({"code": "invalid_slide_spec", "severity": "major", **error} for error in errors)
    if assets_path and not assets_path.is_file():
        report["issues"].append({"code": "asset_manifest_missing", "severity": "major", "path": str(assets_path)})
    if package["ok"] and not report["issues"]:
        checker = content_checker()
        texts, notes = checker.extract_pptx_text(pptx), checker.extract_pptx_notes(pptx)
        report["content"] = checker.check(spec, texts, checker.extract_fact_blocks(pptx)) if spec else {
            "ok": True, "actual_slide_count": len(texts), "issues": [], "blocker_count": 0}
        report["missing_notes"] = [number for number in range(1, len(texts) + 1)
                                   if spec.get("meta", {}).get("include_speaker_notes") and not notes.get(number, "").strip()]
        data = json.loads(assets_path.read_text(encoding="utf-8")) if assets_path and assets_path.is_file() else {"deck": pptx.stem, "assets": []}
        report["assets"] = validate_assets(data, assets_path.parent if assets_path else pptx.parent, texts)
        report["ok"] = report["content"]["ok"] and not report["missing_notes"] and report["assets"]["ok"]
    report["scope"] = "package, explicit content/fact requirements, requested notes and declared assets; visual quality requires actual inspection"
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "report": report}, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
