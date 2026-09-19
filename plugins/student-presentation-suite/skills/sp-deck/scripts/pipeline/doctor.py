"""Environment probe: answer the questions a refusal leaves open.

2026-09-19 live: `plan` refused with "missing successful isolated research
runtime receipt" and the session spent 52 requests (6.5M input tokens, ~50% of
the whole run) probing hooks, logs, settings and finally the upstream GitHub
source to learn what one JSON answer could have said. doctor is that answer:
whether this runtime can produce execution receipts at all, and whether the
local toolchain (python-pptx, pptxgenjs, renderers) is present.

Read-only: doctor never creates, repairs or advances anything.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from pipeline.core import ROOT  # noqa: E402


def _soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    candidates = [
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
        Path("/usr/bin/soffice"),
        Path("/usr/local/bin/soffice"),
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def _guard_dirs(work_dir: Path) -> list[Path]:
    """runtime_evidence writes ledgers under <project>/outputs/.pptx-work/.guard."""
    dirs = [work_dir.parent / ".guard"]
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    if project:
        dirs.append(Path(project) / "outputs" / ".pptx-work" / ".guard")
    return dirs


def check_receipts(work_dir: Path) -> dict[str, Any]:
    guard_ledgers: list[str] = []
    for guard in _guard_dirs(work_dir):
        if guard.is_dir():
            guard_ledgers.extend(sorted(p.name for p in guard.glob("agent-*.json")))
    active_flags: list[str] = []
    for guard in _guard_dirs(work_dir):
        if guard.is_dir():
            active_flags.extend(sorted(p.name for p in guard.glob("research-active-*.json")))
    receipt = work_dir / "research-execution.json"
    pack = work_dir / "research-pack.json"
    if receipt.is_file():
        verdict = "observed"
        advice = "receipts work in this runtime; keep the default --receipt-policy require."
    elif pack.is_file() and guard_ledgers:
        verdict = "incomplete"
        advice = (
            "an agent ledger exists but no receipt: the researcher may still be running or "
            "stopped before SubagentStop. Re-check after the isolated agent returns."
        )
    elif pack.is_file():
        verdict = "unavailable"
        advice = (
            "research-pack.json exists but no SubagentStart ledger was ever written: this "
            "runtime does not deliver subagent hook events to plugin hooks, so receipts "
            "cannot be produced here. Re-run plan/qa with --receipt-policy allow-missing "
            "(degraded mode, recorded in the manifest)."
        )
    elif active_flags:
        verdict = "pending"
        advice = "a researcher spawn is active in this session; re-run doctor after it returns."
    else:
        verdict = "unknown"
        advice = (
            "no isolated researcher run observed yet. After the first researcher run, a "
            "missing agent ledger here means this runtime cannot produce receipts; use "
            "--receipt-policy allow-missing then."
        )
    return {
        "verdict": verdict,
        "receipt_file": str(receipt),
        "receipt_present": receipt.is_file(),
        "research_pack_present": pack.is_file(),
        "guard_ledgers": guard_ledgers[:10],
        "advice": advice,
    }


def check_toolchain() -> dict[str, Any]:
    toolchain: dict[str, Any] = {}
    try:
        import pptx  # noqa: F401

        toolchain["python_pptx"] = True
    except ImportError:
        toolchain["python_pptx"] = False
    try:
        import pymupdf  # noqa: F401

        toolchain["pymupdf"] = True
    except ImportError:
        try:
            import fitz  # noqa: F401

            toolchain["pymupdf"] = True
        except ImportError:
            toolchain["pymupdf"] = False
    toolchain["pdftoppm"] = bool(shutil.which("pdftoppm"))
    soffice = _soffice()
    toolchain["soffice"] = soffice
    node_modules = ROOT / "node_modules" / "pptxgenjs" / "package.json"
    toolchain["pptxgenjs"] = node_modules.is_file() or bool(shutil.which("node"))
    if not toolchain["pptxgenjs"]:
        toolchain["pptxgenjs"] = False
    return toolchain


def check_work_dir(work_dir: Path) -> dict[str, Any]:
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=work_dir, prefix=".doctor-", delete=False) as handle:
            probe = Path(handle.name)
        probe.unlink()
        return {"writable": True, "exists": True}
    except OSError as exc:
        return {"writable": False, "error": str(exc)[:200]}


def run_doctor(work_dir: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "plugin_root": str(ROOT),
        "hook_files_present": {
            "hooks.json": (ROOT / "hooks" / "hooks.json").is_file(),
            "runtime_evidence.py": (ROOT / "scripts" / "runtime_evidence.py").is_file(),
        },
        "receipts": check_receipts(work_dir),
        "toolchain": check_toolchain(),
        "work_dir": {**check_work_dir(work_dir), "path": str(work_dir)},
    }
    advice: list[str] = [report["receipts"]["advice"]]
    if not report["toolchain"]["python_pptx"]:
        advice.append("python-pptx missing: `pip install python-pptx` before build.")
    if not (report["toolchain"]["soffice"] or report["toolchain"]["pdftoppm"] or report["toolchain"]["pymupdf"]):
        advice.append(
            "no renderer found (LibreOffice/PyMuPDF/poppler): rendered QA and complete need one."
        )
    report["advice"] = advice
    return report


def cmd_doctor(args: argparse.Namespace) -> int:
    report = run_doctor(args.work_dir.resolve())
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(f"plugin: {report['plugin_root']}")
    receipts = report["receipts"]
    print(f"receipts: {receipts['verdict']} — {receipts['advice']}")
    print(
        "toolchain: "
        + json.dumps({k: v for k, v in report["toolchain"].items() if k != "soffice"})
        + f" soffice={report['toolchain']['soffice']}"
    )
    print(f"work-dir: {'writable' if report['work_dir']['writable'] else 'NOT writable'} ({report['work_dir']['path']})")
    for item in report["advice"][1:]:
        print(f"note: {item}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    raise SystemExit(cmd_doctor(parser.parse_args()))
