"""Cache identities, separate from content approval and quality decisions."""
from __future__ import annotations

import contextlib
import hashlib
import json
import zipfile
from pathlib import Path

import yaml


def content_digest(path: Path) -> str:
    raw = path.read_bytes()
    if path.suffix.lower() in {".json", ".yaml", ".yml"}:
        try:
            data = json.loads(raw) if path.suffix.lower() == ".json" else yaml.safe_load(raw.decode("utf-8"))
            raw = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (ValueError, UnicodeError, TypeError, yaml.YAMLError):
            pass
    elif path.suffix.lower() == ".md":
        with contextlib.suppress(UnicodeError):
            raw = "\n".join(line.rstrip() for line in raw.decode("utf-8").splitlines()).strip().encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def visual_digest(path: Path) -> str:
    """Hash slide-affecting package parts, excluding notes and ZIP metadata."""
    digest = hashlib.sha256()
    if not zipfile.is_zipfile(path):
        # Cache identity is not package validation; render/validate owns errors.
        return hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as package:
        for name in sorted(package.namelist()):
            if name.startswith(("docProps/", "ppt/notesSlides/", "ppt/notesMasters/")) or name.endswith("/"):
                continue
            digest.update(name.encode("utf-8") + b"\0" + package.read(name))
    return digest.hexdigest()
