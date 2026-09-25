#!/usr/bin/env python3
"""Structured import of user materials: a D-class Research Pack without a researcher.

When the user restricts sourcing to their own material ("only my uploaded paper /
only the course slides"), spawning a web researcher is theater: the isolated
researcher would only re-read local files and stamp a receipt. This tool builds
the same Research Pack deterministically — every source is a hash-bound
`user-file`, `queries` stays empty — and writes an import receipt that `plan`
accepts in place of the researcher runtime receipt. Source recording and
validation are preserved; only the subagent goes away.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import validate_research_pack as validator  # noqa: E402

RECEIPT_TOOL = "import_user_materials.py"


def sha256_file(path: Path) -> str:
    import hashlib  # noqa: PLC0415

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_topic(spec: Path | None) -> str:
    if spec is None or not spec.is_file():
        return "user materials import"
    try:
        text = spec.read_text(encoding="utf-8")
        data = json.loads(text) if spec.suffix.lower() == ".json" else None
        if data is None:
            import yaml  # noqa: PLC0415

            data = yaml.safe_load(text)
        return str(((data or {}).get("meta") or {}).get("topic") or "user materials import")
    except (OSError, ValueError, ImportError):
        return "user materials import"


def build_pack(materials: list[Path], topic: str) -> dict[str, Any]:
    sources = []
    for index, path in enumerate(materials, 1):
        sources.append({
            "id": f"S{index:02d}",
            "title": path.name,
            "type": "user-file",
            "tier": "S",
            "independence_group": path.name,
            "locator": str(path.resolve()),
            "sha256": sha256_file(path),
        })
    return {
        "version": "0.10",
        "topic": topic,
        "pack_author": "import_user_materials",
        "budget": "simple",
        "queries": [],
        "findings": [],
        "sources": sources,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("materials", nargs="+", type=Path, help="user material files to import")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--spec", type=Path, help="Slide Spec for the topic line")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    work_dir = args.work_dir.resolve()
    if work_dir.parent.name != ".pptx-work":
        print("import_user_materials: REFUSED — --work-dir must be outputs/.pptx-work/<work-id>", file=sys.stderr)
        return 2
    missing = [str(path) for path in args.materials if not path.is_file()]
    if missing:
        print(f"import_user_materials: REFUSED — material files not found: {missing}", file=sys.stderr)
        return 2
    if not args.materials:
        print("import_user_materials: REFUSED — at least one material file is required", file=sys.stderr)
        return 2

    pack = build_pack([Path(path) for path in args.materials], load_topic(args.spec))
    report = validator.validate(pack)
    problems = [item for item in report.get("problems") or [] if item.get("severity") in {"critical", "major"}]
    payload = {"ok": not problems, "problems": problems, "inventory": report.get("inventory")}
    if not problems:
        work_dir.mkdir(parents=True, exist_ok=True)
        pack_path = work_dir / "research-pack.json"
        pack_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        validation_path = work_dir / "research-pack-validation.json"
        validation_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        receipt = {
            "tool": RECEIPT_TOOL,
            "work_id": work_dir.name,
            "at": datetime.now(UTC).isoformat(),
            "files": [
                {"path": str(Path(str(source["locator"]))), "sha256": source["sha256"]}
                for source in pack["sources"]
            ],
            "pack": {"path": str(pack_path), "sha256": sha256_file(pack_path)},
        }
        receipt_path = work_dir / "research-import.json"
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        payload.update({
            "pack": str(pack_path),
            "validation": str(validation_path),
            "import_receipt": str(receipt_path),
            "sources": len(pack["sources"]),
        })
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if payload["ok"]:
            print(
                f"import_user_materials: ok — {payload['sources']} user-file source(s) "
                f"imported into {payload['pack']}"
            )
        else:
            print("import_user_materials: REFUSED — " + json.dumps(problems, ensure_ascii=False)[:400], file=sys.stderr)
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
