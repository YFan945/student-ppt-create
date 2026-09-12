#!/usr/bin/env python3
"""Fail npm audit on any unreviewed advisory while allowing time-bounded exceptions."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GHSA_RE = re.compile(r"GHSA-[0-9a-z-]+", re.IGNORECASE)

# image-size has no installable patched release as of 2026-09-08. These
# exceptions are deliberately narrow and expire so CI cannot hide future risk.
ALLOWLIST = {
    "ghsa-w3rx-r6r6-pgpr": {
        "package": "image-size",
        "review_due": dt.date(2026, 10, 1),
        "reason": "No patched npm release is currently installable; reached through PPTX image metadata handling.",
    },
    "ghsa-5p2g-fcmc-qvqq": {
        "package": "image-size",
        "review_due": dt.date(2026, 10, 1),
        "reason": "No patched npm release is currently installable; reached through PPTX image metadata handling.",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run npm audit and allow only explicit, unexpired advisory exceptions"
    )
    parser.add_argument(
        "--package-dir",
        type=Path,
        default=ROOT,
        help="Directory containing package.json/package-lock.json",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser.parse_args()


def advisory_id(item: dict[str, Any]) -> str | None:
    for value in (item.get("url"), item.get("title"), item.get("name")):
        match = GHSA_RE.search(str(value or ""))
        if match:
            return match.group(0).lower()
    return None


def collect_advisories(payload: dict[str, Any]) -> list[dict[str, Any]]:
    advisories: list[dict[str, Any]] = []
    vulnerabilities = payload.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        return advisories
    for package_name, vulnerability in vulnerabilities.items():
        if not isinstance(vulnerability, dict):
            continue
        via = vulnerability.get("via")
        if not isinstance(via, list):
            continue
        for item in via:
            if not isinstance(item, dict):
                continue
            ghsa = advisory_id(item)
            advisories.append(
                {
                    "id": ghsa,
                    "package": str(item.get("name") or package_name),
                    "severity": str(item.get("severity") or vulnerability.get("severity") or "unknown"),
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "range": str(item.get("range") or vulnerability.get("range") or ""),
                }
            )
    unique: dict[tuple[str | None, str, str], dict[str, Any]] = {}
    for item in advisories:
        key = (item["id"], item["package"], item["title"])
        unique[key] = item
    return list(unique.values())


def evaluate(advisories: list[dict[str, Any]], today: dt.date) -> dict[str, Any]:
    allowed: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in advisories:
        key = str(item.get("id") or "").lower()
        exception = ALLOWLIST.get(key)
        if (
            exception
            and item.get("package") == exception["package"]
            and today <= exception["review_due"]
        ):
            allowed.append(
                {
                    **item,
                    "review_due": exception["review_due"].isoformat(),
                    "reason": exception["reason"],
                }
            )
        else:
            blocked.append(item)
    return {
        "ok": not blocked,
        "date": today.isoformat(),
        "allowed": allowed,
        "blocked": blocked,
    }


def main() -> int:
    args = parse_args()
    package_dir = args.package_dir.resolve()
    proc = subprocess.run(
        ["npm", "audit", "--json"],
        cwd=package_dir,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(proc.stdout, file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        print("npm audit did not return valid JSON", file=sys.stderr)
        return 2

    advisories = collect_advisories(payload)
    result = evaluate(advisories, dt.date.today())
    result["npm_audit_exit_code"] = proc.returncode
    result["metadata"] = payload.get("metadata", {})

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"npm audit gate: {'PASS' if result['ok'] else 'FAIL'} "
            f"({len(result['allowed'])} reviewed exception(s), {len(result['blocked'])} blocker(s))"
        )
        for item in result["allowed"]:
            print(
                f"ALLOW {item['id']} {item['package']} until {item['review_due']}: "
                f"{item['title']}"
            )
        for item in result["blocked"]:
            print(
                f"BLOCK {item.get('id') or 'unknown'} {item['package']} "
                f"[{item['severity']}]: {item['title']}"
            )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
