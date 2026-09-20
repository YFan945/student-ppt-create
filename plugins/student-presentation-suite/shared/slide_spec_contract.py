"""Reusable loading, hashing, and validation for Slide Spec artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from shared.slide_spec_validation import semantic_errors

DEFAULT_SCHEMA = Path(__file__).resolve().parents[1] / "references" / "slide-spec.schema.json"


def load_slide_spec(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix.casefold() == ".json" else yaml.safe_load(text)


def validate_slide_spec(
    path: Path,
    schema_path: Path = DEFAULT_SCHEMA,
) -> tuple[Any, list[dict[str, str]], str]:
    """Validate one on-disk spec and return data, normalized errors, and file hash."""
    raw = path.read_bytes()
    data = load_slide_spec(path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    schema_errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    errors: list[dict[str, str]] = []
    for error in schema_errors:
        parts = list(error.path)
        message = error.message
        if parts and parts[-1] == "slide_copy" and isinstance(error.instance, dict):
            message = (
                "slide_copy must be a string or string[]; objects such as "
                "{title, subtitle} are unsupported — flatten the visible copy to a list"
            )
        errors.append(
            {
                "path": "." + ".".join(str(part) for part in parts),
                "message": message,
            }
        )
    if not errors:
        errors.extend(semantic_errors(data))
    return data, errors, hashlib.sha256(raw).hexdigest()
