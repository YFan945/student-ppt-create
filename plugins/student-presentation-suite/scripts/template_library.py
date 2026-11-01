#!/usr/bin/env python3
"""Index/search local templates or assemble selected editable slides on a copy."""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.template_library import ROLES, assemble, build_catalog, inspect_template, search_catalog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    index = sub.add_parser("index")
    index.add_argument("--template-dir", type=Path, action="append", required=True)
    index.add_argument("--preview-dir", type=Path, action="append", default=[])
    index.add_argument("--output", type=Path, required=True)
    search = sub.add_parser("search")
    search.add_argument("catalog", type=Path)
    search.add_argument("--query", default="")
    search.add_argument("--role", choices=ROLES)
    search.add_argument("--limit", type=int, default=12)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("source", type=Path)
    inspect.add_argument("--slide", type=int)
    merge = sub.add_parser("assemble")
    merge.add_argument("selection", type=Path, help='JSON array of {path,slide,reason}; relative paths use this file directory')
    merge.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if hasattr(args, "output") and args.output.resolve().is_relative_to(ROOT.parent.parent):
            raise ValueError("template artifacts belong in the active project outputs, outside the marketplace")
        if args.command == "index":
            if not all(path.is_dir() for path in args.template_dir + args.preview_dir):
                raise ValueError("template/preview directories must exist")
            result = build_catalog(args.template_dir, args.preview_dir)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            result = {"catalog": str(args.output.resolve()), "templates": len(result["templates"]), "errors": result["errors"]}
        elif args.command == "search":
            if args.limit < 1:
                raise ValueError("limit must be positive")
            result = {"matches": search_catalog(json.loads(args.catalog.read_text(encoding="utf-8-sig")), args.query, args.role, args.limit)}
        elif args.command == "inspect":
            result = inspect_template(args.source)
            if args.slide is not None:
                if not 1 <= args.slide <= result["slide_count"]:
                    raise ValueError("slide number out of range")
                result["slides"] = [result["slides"][args.slide - 1]]
        else:
            selection = json.loads(args.selection.read_text(encoding="utf-8-sig"))
            for item in selection:
                item["path"] = str((args.selection.resolve().parent / item["path"]).resolve())
            if args.output.resolve().is_relative_to(ROOT.parent.parent):
                raise ValueError("template artifacts belong in the active project's outputs, outside the marketplace")
            result = assemble(selection, args.output)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
