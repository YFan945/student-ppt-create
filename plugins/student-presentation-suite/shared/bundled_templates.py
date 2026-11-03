"""Portable design references: previews and editable-object layout recipes.

No original PPTX, fonts, personal image files or absolute machine paths are
needed at runtime. Example text/data are untrusted, not task instructions.
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any

from shared.hashing import file_sha256

BUNDLED_ROOT = Path(__file__).resolve().parents[1] / "assets" / "template-library"


def asset_path(value: str, root: Path | None = None) -> Path:
    root = (root or BUNDLED_ROOT).resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"bundled reference asset missing or outside library: {value}")
    return path


def catalog_path() -> Path:
    return BUNDLED_ROOT / "catalog.json"


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    path = path or catalog_path()
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if result.get("kind") == "bundled-design-references":
        root = path.resolve().parent
        for entry in result["templates"]:
            if entry.get("preview"):
                entry["preview"] = str(asset_path(entry["preview"], root))
            if entry.get("recipe"):
                entry["recipe"] = str(asset_path(entry["recipe"], root))
            for slide in entry.get("slides", []):
                if slide.get("preview"):
                    slide["preview"] = str(asset_path(slide["preview"], root))
    return result


def metadata(source: str) -> dict[str, Any]:
    key = source.removeprefix("builtin:")
    catalog = load_catalog()
    entry = next((item for item in catalog["templates"] if item["id"] == key), None)
    if entry is None:
        raise ValueError(f"unknown built-in reference: {key}; search the bundled catalog first")
    return entry


def reference(source: str, slide: int | None = None) -> dict[str, Any]:
    entry = metadata(source)
    key = entry["id"]
    if slide is not None and (isinstance(slide, bool) or not 1 <= slide <= entry["slide_count"]):
        raise ValueError(f"built-in reference page out of range: {key}/{slide}")
    result = dict(entry)
    result["binding_paths"] = [str(catalog_path())]
    if entry.get("recipe"):
        result["binding_paths"].append(entry["recipe"])
        with gzip.open(entry["recipe"], "rt", encoding="utf-8") as stream:
            recipe = json.load(stream)
        pages = recipe["slides"]
        result["slides"] = [page for page in pages if slide is None or page["slide"] == slide]
        dependencies = {key for page in result["slides"] for key in page.get("inherits", [])}
        result["inherited_components"] = {key: value for key, value in recipe.get("inherited_components", {}).items() if key in dependencies}
    elif slide is not None:
        result["slides"] = [page for page in entry["slides"] if page["slide"] == slide]
    # Attach the appropriate preview, resolved at the current installation.
    previews = {page["slide"]: page.get("preview") for page in entry.get("slides", [])}
    for page in result.get("slides", []):
        page["preview"] = previews.get(page["slide"]) or entry.get("preview")
    result["scope"] = "Design reference only. Replace example text/data/images; rebuild separate editable objects. Not a reusable original PPTX package."
    return result


def authoring_references(spec: dict[str, Any], page: dict[str, Any], work: Path) -> list[dict[str, Any]]:
    """Resolve chosen recipes into author inputs, not just catalog hints."""
    sources = {s["id"]: s for s in spec.get("template_sources", [])}
    selected = []
    for ref in page.get("template_refs", []):
        source = sources.get(ref["source_id"], {})
        if not source.get("path", "").startswith("builtin:"):
            continue
        recipe = reference(source["path"], ref["slide"])
        destination = work / "inputs" / "template-references" / f"{recipe['id']}-{ref['slide']}.json"
        data = {"scope": recipe["scope"], "size_emu": recipe.get("size_emu"),
                "slides": recipe["slides"], "inherited_components": recipe.get("inherited_components", {})}
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file() or destination.read_text(encoding="utf-8") != text:
            destination.write_text(text, encoding="utf-8")
        selected.append({**ref, "path": source["path"], "preview": recipe["slides"][0].get("preview"),
                         "recipe_path": str(destination),
                         "instruction": "Read this selected page's geometry, groups, type and inherited components; adapt them to task content. Example facts/identities are not task facts. Compare the actual reference and final render."})
    return selected


def suggestions(spec: dict[str, Any], limit: int = 6) -> dict[str, Any]:
    from shared.template_library import ROLES, search_catalog

    catalog = load_catalog()
    topic = (spec.get("meta") or {}).get("topic", "")
    if not any(term in topic for term in ("党", "政治", "红色")):
        catalog["templates"] = [entry for entry in catalog["templates"] if entry.get("category") != "party"]
    mapping = {"chart": "data", "table": "comparison", "comparison": "comparison",
               "timeline": "timeline", "process": "process", "architecture": "process",
               "image": "photo", "photo": "photo", "screenshot": "evidence"}
    by_slide = []
    for index, page in enumerate(spec.get("slides", []), 1):
        text = " ".join(str(page.get(k, "")) for k in ("title", "claim", "content", "visual", "semantic_requirements"))
        role = mapping.get((page.get("visual") or {}).get("type"))
        kind = str(page.get("kind") or page.get("role") or "").lower()
        if kind == "cover" or (index == 1 and not kind):
            role = "cover"
        elif not role:
            roles = ("process", "comparison", "timeline", "data", "photo", "evidence")
            title = str(page.get("title", ""))
            role = next((r for r in roles if re.search(ROLES[r], title, re.I)), None)
            role = role or next((r for r in roles if re.search(ROLES[r], text, re.I)), "evidence")
        # Topic terms improve relevance where they exist; role-only fallback is
        # deliberate: a finance layout can support energy data after adaptation.
        query = " ".join([topic, str(page.get("title", "")),
                          *re.findall(ROLES.get(role, ""), text, re.I)])
        matches = search_catalog(catalog, query, role, 3) or search_catalog(catalog, "", role, 3)
        by_slide.append({"slide": page.get("id", index), "role": role, "query": query,
                         "candidates": matches})
    # Round-robin page needs before limiting. Do not collapse all body layouts
    # from one useful source to its first page, or truncate the whole catalog.
    unique = {}
    for rank in range(3):
        for page in by_slide:
            for item in page["candidates"][rank:rank + 1]:
                unique.setdefault((item["source_id"], item["slide"]), item)
    return {"catalog": str(catalog_path()), "source_count": len(load_catalog()["templates"]),
            "candidates": list(unique.values())[:limit], "by_slide": by_slide,
            "next": "Choose cover and body references before authoring. View real previews (a text description is not a viewed image), read selected recipes, record template_sources/template_refs and adapt editable objects. Return to a reference when the result loses its structure."}


def validate_bundle(root: Path | None = None) -> dict[str, Any]:
    root = root or BUNDLED_ROOT
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8"))
    errors = []
    seen = set()
    for entry in catalog["templates"]:
        if entry["id"] in seen:
            errors.append(f"duplicate source id: {entry['id']}")
        seen.add(entry["id"])
        assets = [(entry.get("recipe"), entry.get("recipe_sha256")),
                  (entry.get("preview"), entry.get("preview_sha256"))]
        assets += [(page.get("preview"), page.get("preview_sha256")) for page in entry.get("slides", [])]
        for value, expected in assets:
            if not value:
                continue
            try:
                path = asset_path(value, root)
                if not expected or file_sha256(path) != expected:
                    errors.append(f"bundled reference checksum mismatch: {value}")
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
        if entry.get("path") != f"builtin:{entry['id']}":
            errors.append(f"nonportable source path: {entry['id']}")
    return {"ok": not errors, "source_count": len(seen), "errors": errors}
