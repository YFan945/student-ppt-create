#!/usr/bin/env python3
"""Validate Student Presentation Slide Spec YAML."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.handoff_validation import handoff_errors
from shared.slide_spec_contract import validate_slide_spec
from shared.slide_spec_validation import planning_warnings


def load_optional_dependencies():
    try:
        import jsonschema
        import yaml
    except ImportError as exc:
        print(
            "Missing dependency. Install plugin validation dependencies with: "
            "python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(3) from exc
    return jsonschema, yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Slide Spec YAML")
    parser.add_argument("spec", type=Path, help="Slide Spec YAML file")
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "references" / "slide-spec.schema.json",
        help="JSON Schema path",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON result")
    parser.add_argument("--output", type=Path, help="Write a reusable validation report")
    parser.add_argument(
        "--brief",
        type=Path,
        help="Optional validated Presentation Brief to check against the Slide Spec",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    jsonschema, yaml = load_optional_dependencies()
    try:
        data, errors, spec_hash = validate_slide_spec(args.spec, args.schema)
        if not errors and args.brief:
            raw = args.brief.read_text(encoding="utf-8")
            brief = json.loads(raw) if args.brief.suffix.lower() == ".json" else yaml.safe_load(raw)
            brief_schema = json.loads(
                (ROOT / "references" / "presentation-brief.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            validator = jsonschema.Draft202012Validator(brief_schema)
            for error in sorted(
                validator.iter_errors(brief),
                key=lambda item: tuple(str(part) for part in item.path),
            ):
                location = ".brief" + "".join(f"[{part!r}]" for part in error.path)
                errors.append({"path": location, "message": error.message})
            if not errors:
                errors.extend(handoff_errors(brief, data))
    except (OSError, json.JSONDecodeError, yaml.YAMLError, jsonschema.SchemaError) as exc:
        result = {"valid": False, "error": str(exc), "errors": []}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Slide Spec validation failed: {exc}")
        raise SystemExit(2) from exc

    result = {
        "valid": not errors,
        "error_count": len(errors),
        "errors": errors,
        "warnings": planning_warnings(data) if not errors else [],
        "slide_spec": str(args.spec.resolve()),
        "slide_spec_sha256": spec_hash,
        "presentation_brief": str(args.brief.resolve()) if args.brief else None,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif errors:
        print("Slide Spec is invalid:")
        for error in result["errors"]:
            print(f"- {error['path']}: {error['message']}")
    else:
        print("Slide Spec is valid.")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
