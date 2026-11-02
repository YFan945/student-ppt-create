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

from shared.research_io import atomic_json  # noqa: E402


def inspect(work: Path) -> dict:
    work = work.resolve()
    pack_path = work / "research-pack.json"
    validation_path = work / "research-pack-validation.json"
    try:
        pack = validator.normalize(validator.load(pack_path))
        fetched_path = work / "research/fetched/fetch-text-report.json"
        fetched = validator._coerce_trail(fetched_path, "fetch-report")[0] if fetched_path.is_file() else None
        verdict = validator.validate(pack, fetch_report=fetched, work_dir=work)
        apply_task(verdict, pack, work)
        errors = [p["message"] for p in verdict["problems"] if p["severity"] in {"major", "critical"}]
        verdict["research_pack_sha256"] = validator.sha256_file(pack_path)
        atomic_json(validation_path, verdict)
        receipt_path = work / "research-execution.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            receipt = {}
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
