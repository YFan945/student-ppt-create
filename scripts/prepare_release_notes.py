"""Extract the current manifest version's changelog; refuse missing release notes."""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def release_notes() -> str:
    version = json.loads((ROOT / "plugins/student-presentation-suite/.claude-plugin/plugin.json").read_text())["version"]
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## " + re.escape(version) + r" — [^\n]+\n(.*?)(?=^## |\Z)", changelog, re.MULTILINE | re.DOTALL)
    if not match or not match[1].strip():
        raise SystemExit("Current version must have dated release notes before publication")
    return match[1].strip() + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(release_notes(), encoding="utf-8")
