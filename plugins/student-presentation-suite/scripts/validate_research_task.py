#!/usr/bin/env python3
"""Validate the path-only handoff before starting a researcher."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]


def validate_task(task: dict, task_path: Path) -> list[str]:
    schema = json.loads((ROOT / "references/research-task.schema.json").read_text(encoding="utf-8"))
    errors = [error.message for error in jsonschema.Draft202012Validator(schema).iter_errors(task)]
    if errors:
        return errors
    work = Path(task["work_dir"])
    if not work.is_absolute() or work.resolve() != task_path.resolve().parent:
        errors.append("work_dir must be absolute and contain research-task.json")
    if work.name != task["work_id"] or work.parent.name != ".pptx-work" or work.parent.parent.name != "outputs":
        errors.append("work_dir must be outputs/.pptx-work/<work_id>")
    marketplace = ROOT.parents[1]
    if work.resolve().is_relative_to(ROOT) or work.resolve().is_relative_to(marketplace):
        errors.append("research outputs must not be written inside the plugin or marketplace")
    for key in ("brief_path", "materials_path"):
        value = task.get(key)
        if value and (not Path(value).is_absolute() or not Path(value).exists()):
            errors.append(f"{key} must name an existing absolute path")
    if task["scope"] == "D" and not task.get("materials_path"):
        errors.append("D scope requires materials_path")
    ids = [entry["id"] for entry in task["claims"]]
    if len(ids) != len(set(ids)):
        errors.append("claim ids must be unique")
    if task["scope"] in {"A", "B"} and not ids:
        errors.append("A/B scope requires at least one claim")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", type=Path)
    args = parser.parse_args()
    try:
        task = json.loads(args.task.read_text(encoding="utf-8"))
        errors = validate_task(task, args.task)
    except (OSError, ValueError) as exc:
        errors = [str(exc)]
    print(json.dumps({"ok": not errors, "problems": errors}, ensure_ascii=False))
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
