"""Check the complete researcher handoff in one local call; print metadata only."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import validate_research_pack as validator  # noqa: E402
from research_task_binding import apply_task  # noqa: E402


def inspect(work: Path) -> dict:
    work = work.resolve()
    pack_path = work / "research-pack.json"
    validation_path = work / "research-pack-validation.json"
    try:
        pack = validator.load(pack_path)
        saved = json.loads(validation_path.read_text(encoding="utf-8"))
        receipt = json.loads((work / "research-execution.json").read_text(encoding="utf-8"))
        fetched_path = work / "research/fetched/fetch-text-report.json"
        fetched = json.loads(fetched_path.read_text(encoding="utf-8")) if fetched_path.is_file() else None
        verdict = validator.validate(pack, fetch_report=fetched, work_dir=work)
        apply_task(verdict, pack, work)
        errors = [p["message"] for p in verdict["problems"] if p["severity"] in {"major", "critical"}]
        digest = validator.sha256_file(pack_path)
        if not saved.get("ok") or saved.get("research_pack_sha256") != digest:
            errors.append("Validation report is missing, failing or stale")
        if verdict.get("task") != saved.get("task"):
            errors.append("Validation task binding is stale")
        artifact = receipt.get("artifact", {})
        if not receipt.get("spawn_verified") or not str(receipt.get("agent", "")).endswith(":presentation-researcher"):
            errors.append("Genuine researcher execution receipt is missing")
        if artifact.get("sha256") != digest or Path(artifact.get("path", "")).resolve() != pack_path:
            errors.append("Research execution receipt does not bind the current pack")
        return {"ok": not errors, "delivery_status": verdict["delivery_status"],
                "pack": str(pack_path), "validation": str(validation_path),
                "core_gaps": verdict["core_gaps"], "pending_claims": verdict["pending_claims"],
                "counts": verdict["inventory"], "retrieval": receipt.get("retrieval", {}),
                "problems": errors}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "delivery_status": "insufficient", "problems": [str(exc)]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    report = inspect(parser.parse_args().work_dir)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
