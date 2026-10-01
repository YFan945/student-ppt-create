"""Run real Claude research cases and retain per-case coverage and failures."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = (("multi-cn", "research-multi-cn.brief.md", "ready", True),
         ("cross-check", "research-cross-check.brief.md", "ready", True),
         ("gap", "research-gap.brief.md", "partial", False))


def summarize(payload: dict, events: list[dict], expected: str, require_search: bool) -> dict:
    work = Path(payload["pack_path"]).parent
    pack = json.loads((work / "research-pack.json").read_text(encoding="utf-8"))
    report = json.loads((work / "research-pack-validation.json").read_text(encoding="utf-8"))
    task = json.loads((work / "research-task.json").read_text(encoding="utf-8"))
    calls = [block for event in events if event.get("type") == "assistant"
             for block in event.get("message", {}).get("content", []) if block.get("type") == "tool_use"]
    searches = sum(c.get("name") == "WebSearch" for c in calls)
    log_path = work / "research/search-log.json"
    logs = json.loads(log_path.read_text(encoding="utf-8")).get("search_executions", []) if log_path.is_file() else []
    fetch_path = work / "research/fetched/fetch-text-report.json"
    fetched = json.loads(fetch_path.read_text(encoding="utf-8")).get("records", []) if fetch_path.is_file() else []
    checks = {"isolated": payload.get("mechanism_ok") is True,
              "valid": report.get("ok") is True,
              "semantic_review_requested": task.get("semantic_review_required") is True,
              "expected_delivery": report.get("delivery_status") == expected,
              "websearch_exercised": searches > 0 if require_search else True}
    if expected == "partial":
        checks["missing_page_exercised"] = any(r.get("url") == "https://docs.python.org/3/library/nonexistent-research-acceptance-2026.html" and not r.get("ok") for r in fetched)
    return {"checks": checks, "passed": all(checks.values()), "delivery_status": report.get("delivery_status"),
            "core_gaps": report.get("core_gaps"), "duration_seconds": payload.get("duration_ms", 0) / 1000,
            "reported_cost_usd": payload.get("total_cost_usd"), "tool_calls": len(calls),
            "websearch_calls": searches, "logged_searches": len(logs),
            "failed_searches": sum(e.get("status") == "failed" for e in logs),
            "failed_fetches": sum(not r.get("ok") for r in fetched),
            "permission_denials": payload.get("permission_denials", []),
            "claims": [{"id": c.get("id"), "status": c.get("status")} for c in pack.get("must_verify", [])],
            "work_dir": str(work)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case", choices=[c[0] for c in CASES])
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, brief, expected, require_search in CASES:
        if args.case and name != args.case:
            continue
        output = args.output_dir / (name + ".json")
        command = [sys.executable, str(ROOT / "scripts/smoke_research_fork.py"),
                   "--plugin-dir", str(ROOT), "--brief-file", str(ROOT / "scripts/live_prompts" / brief),
                   "--scope", "B", "--max-budget-usd", "3",
                   "--stream", "--validate", "--json", "--timeout-seconds", "420", "--output", str(output)]
        print("Running " + name, flush=True)
        try:
            run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
            (args.output_dir / (name + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
            payload = json.loads(run.stdout)
            events = [json.loads(line) for line in output.with_suffix(".stream.jsonl").read_text(encoding="utf-8").splitlines() if line.startswith("{")]
            if not payload.get("artifact_ok"):
                row = {"passed": False, "mechanism_ok": payload.get("mechanism_ok"),
                       "duration_seconds": payload.get("duration_ms", 0) / 1000,
                       "error": payload.get("result", payload.get("artifact_note")), "work_dir": str(Path(payload["pack_path"]).parent)}
            else:
                row = summarize(payload, events, expected, require_search)
            row["exit_code"] = run.returncode
            row["passed"] = row["passed"] and run.returncode == 0
        except (subprocess.TimeoutExpired, OSError, ValueError, KeyError) as exc:
            row = {"passed": False, "error": str(exc)}
        rows.append({"case": name, **row})
        report = {"passed": all(r["passed"] for r in rows), "cases": rows,
                  "limit": "One real run per case; no population success rate or universal latency guarantee. Gap uses an intentional missing URL."}
        (args.output_dir / "matrix.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    return 0 if all(r["passed"] for r in rows) else 2


if __name__ == "__main__":
    raise SystemExit(main())
