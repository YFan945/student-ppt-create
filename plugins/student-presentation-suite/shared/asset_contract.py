"""Shared asset validation, including intentionally designed placeholders."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA = Path(__file__).resolve().parents[1] / "references" / "asset-manifest.schema.json"


def validate_assets(data: dict[str, Any], directory: Path, slide_texts: list[str] | None = None) -> dict[str, Any]:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = [{"path": "/".join(map(str, error.absolute_path)), "message": error.message}
              for error in Draft202012Validator(schema).iter_errors(data)]
    placeholders = []
    files = []
    if errors:
        return {"ok": False, "errors": errors, "placeholders": placeholders, "files": files}
    for index, asset in enumerate(data["assets"]):
        prefix = f"assets/{index}"
        intended = asset.get("placeholder")
        declared = str(asset["source"]).startswith("placeholder:")
        if declared != bool(intended):
            errors.append({"path": prefix, "message": "placeholder source and placeholder record must agree"})
        if intended:
            if data.get("placeholder_policy", "forbid") != "allow":
                errors.append({"path": prefix, "message": "designed placeholders need confirmed allow policy"})
            if asset["permission"] not in {"suite-original", "generated"}:
                errors.append({"path": prefix, "message": "placeholder must not claim factual/licensed provenance"})
            if asset["permission"] == "generated" and not str(asset.get("prompt") or "").strip():
                errors.append({"path": prefix, "message": "generated placeholder needs its generation prompt"})
            if not all(str(intended[key]).strip() for key in ("label", "replacement", "reason")):
                errors.append({"path": prefix, "message": "placeholder label, replacement and reason must be substantive"})
            placeholders.append({"slide": asset["slide"], **intended})
            if slide_texts is not None:
                number = asset["slide"]
                label = "".join(intended["label"].split())
                if number > len(slide_texts) or label not in "".join(slide_texts[number - 1].split()):
                    errors.append({"path": prefix, "message": "placeholder label must be visible on its declared slide"})
        raw = asset.get("path")
        if raw:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = directory / path
            if not path.is_file():
                errors.append({"path": f"{prefix}/path", "message": "asset file does not exist"})
            else:
                files.append(str(path.resolve()))
                if not asset.get("width") or not asset.get("height"):
                    errors.append({"path": prefix, "message": "file assets require width and height"})
                try:
                    from PIL import Image
                    with Image.open(path) as image:
                        if image.size != (asset.get("width"), asset.get("height")):
                            errors.append({"path": prefix, "message": "declared dimensions differ from actual image"})
                except (OSError, ValueError):
                    pass  # Vector assets retain caller-provided dimensions.
        protected, crop = asset.get("preserve_region"), asset.get("crop")
        for name, region in (("preserve_region", protected), ("crop", crop)):
            if (isinstance(region, dict) and all(key in region for key in ("x", "y", "w", "h"))
                    and (region["x"] + region["w"] > 1 or region["y"] + region["h"] > 1 or region["w"] <= 0 or region["h"] <= 0)):
                errors.append({"path": f"{prefix}/{name}", "message": "normalized region must stay inside image"})
        if (protected and crop and all(key in crop for key in ("x", "y", "w", "h"))
                and not (crop["x"] <= protected["x"] and crop["y"] <= protected["y"]
                    and crop["x"] + crop["w"] >= protected["x"] + protected["w"]
                    and crop["y"] + crop["h"] >= protected["y"] + protected["h"])):
            errors.append({"path": f"{prefix}/crop", "message": "asset_crop_invalid: protected information would be cropped"})
    if slide_texts is not None:
        for number, text in enumerate(slide_texts, 1):
            if "素材待替换" in "".join(text.split()) and not any(item["slide"] == number for item in placeholders):
                errors.append({"path": f"slides/{number}", "message": "visible designed placeholder needs its asset record"})
    return {"ok": not errors, "errors": errors, "placeholders": placeholders, "files": files}
