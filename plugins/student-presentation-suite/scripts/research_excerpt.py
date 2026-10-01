"""Extract an exact bounded passage, optionally updating an existing binding."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.research_io import atomic_json  # noqa: E402


def extract(path: Path, start: str, end: str, max_chars: int = 2000) -> dict:
    if not 1 <= max_chars <= 2000 or not start or not end:
        raise ValueError("Use literal start/end markers and max_chars in 1..2000")
    path = path.resolve()
    if "research" not in path.parts:
        raise ValueError("Text must be under the research directory")
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    i = text.find(start)
    j = text.find(end, i) if i >= 0 else -1
    if i < 0 or j < 0:
        raise ValueError("Literal markers not found; inspect a bounded Read/Grep result")
    excerpt = text[i:j + len(end)]
    if len(excerpt) > max_chars:
        raise ValueError("Passage exceeds the bound; narrow the markers")
    return {"excerpt": excerpt, "text_path": str(path), "text_sha256": hashlib.sha256(raw).hexdigest(),
            "locator": f"characters {i}:{j + len(end)}"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--max-chars", type=int, default=2000)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--entity-id")
    parser.add_argument("--source-id")
    args = parser.parse_args()
    try:
        result = extract(args.text, args.start, args.end, args.max_chars)
        if args.pack:
            pack_path = args.pack.resolve()
            if not args.entity_id or not args.source_id or not args.text.resolve().is_relative_to(pack_path.parent / "research"):
                raise ValueError("Updating a binding requires entity/source ids and text inside this pack's research directory")
            pack = json.loads(pack_path.read_text(encoding="utf-8"))
            matches = [e for e in pack.get("evidence", []) if e.get("entity_id") == args.entity_id and e.get("source_id") == args.source_id]
            if len(matches) != 1:
                raise ValueError("Exactly one existing evidence binding must match")
            matches[0].update(result)
            atomic_json(pack_path, pack)
            result = {"updated": True, "entity_id": args.entity_id, "source_id": args.source_id,
                      "characters": len(result["excerpt"]), "text_sha256": result["text_sha256"]}
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"research_excerpt: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
