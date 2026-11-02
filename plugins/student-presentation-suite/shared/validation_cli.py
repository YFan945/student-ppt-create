"""Public compatibility CLI: technical checks without legacy review paperwork."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shared.artifact_validation import validate_artifact
from shared.slide_spec_contract import load_slide_spec, validate_slide_spec


def main(kind: str = "quality", argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the actual PPTX and requested outputs; scores and audit receipts are optional.")
    parser.add_argument("--pptx", required=kind not in {"planning", "batch"}, type=Path)
    parser.add_argument("--slide-spec", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--preview", type=Path, action="extend", nargs="+", default=[])
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--notes", type=Path)
    parser.add_argument("--full-script", type=Path)
    parser.add_argument("--teleprompter", type=Path)
    parser.add_argument("--asset-manifest", type=Path)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--deliverables")
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--candidates", nargs="+")
    parser.add_argument("--lock-file")
    parser.add_argument("--quality")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--max-items", type=int)
    # Accept historical invocations without reviving their hash/score gates.
    for option in ("spec-lock", "art-direction", "visual-generation-report", "quality-report", "package-report",
                   "slide-spec-report", "actual-content-report", "visual-review-report", "visual-report", "qa-manifest",
                   "tokens", "rhythm-plan", "revision-manifest"):
        parser.add_argument("--" + option)
    for option in ("strict", "visual-reviewed", "simple-mode", "allow-missing-notes", "allow-missing-preview", "lenient"):
        parser.add_argument("--" + option, action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.pptx:
            asset_path = args.asset_manifest or args.pptx.parent / "asset-manifest.json"
            report = validate_artifact(args.pptx, args.slide_spec, original=args.original,
                                       assets_path=asset_path if asset_path.is_file() or args.asset_manifest else None)
        elif args.slide_spec:
            _, errors, _ = validate_slide_spec(args.slide_spec)
            report = {"ok": not errors, "issues": errors, "state": "planned", "artifact_checked": False,
                      "scope": "planning structure only; no visual score, quota, frozen lock or receipt is required"}
        else:
            report = {"ok": False, "issues": [{"code": "input_missing", "message": "provide --pptx or --slide-spec"}]}
        report.update(kind=kind, visual_quality_verified=False)
        if kind == "delivery" and report["ok"]:
            spec = load_slide_spec(args.slide_spec) if args.slide_spec else {}
            meta = spec.get("meta") or {}
            selected = {item.strip() for item in args.deliverables.split(",")} if args.deliverables else set(meta.get("deliverables") or meta.get("export_formats") or ["pptx"])
            selected.update(name for name, path in (("pdf", args.pdf), ("speaker-notes", args.notes),
                            ("full-script", args.full_script), ("teleprompter", args.teleprompter)) if path is not None)
            if args.preview:
                selected.add("preview")
            suffixes = {"pdf": (args.pdf, ".pdf"), "speaker-notes": (args.notes, "-speaker-notes.md"),
                        "full-script": (args.full_script, "-full-script.md"), "teleprompter": (args.teleprompter, "-teleprompter.html")}
            suffixes.update({name: (None, suffix) for name, suffix in {
                "outline": "-outline.md", "quality-report": "-quality-report.json",
                "slide-spec": "-slide-spec" + (args.slide_spec.suffix if args.slide_spec else ".json"), "change-summary": "-change-summary.md",
                "revision-manifest": "-revision-manifest.json", "training-cards": "-training-cards.md",
                "references": "-references.md", "contact-sheet": "-contact-sheet.png"}.items()})
            unknown = selected - {"pptx", "preview", *suffixes}
            report["issues"].extend({"severity": "major", "code": "unknown_deliverable", "output": name} for name in sorted(unknown))
            for name in selected & suffixes.keys():
                explicit, suffix = suffixes[name]
                path = explicit or args.pptx.with_name(args.pptx.stem + suffix)
                if not path.is_file():
                    report["issues"].append({"severity": "major", "code": "requested_output_missing", "output": name, "path": str(path)})
            if "preview" in selected:
                previews = args.preview or list(args.pptx.with_name(args.pptx.stem + "-slides").glob("slide-*.png"))
                expected = report.get("content", {}).get("actual_slide_count", 0)
                if len(previews) != expected or any(not path.is_file() for path in previews):
                    report["issues"].append({"severity": "major", "code": "requested_previews_missing"})
            report["ok"] = not report["issues"]
    except (OSError, ValueError, TypeError) as exc:
        report = {"ok": False, "issues": [{"severity": "critical", "code": "unreadable_input", "message": str(exc)}]}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{kind}: {'ok' if report['ok'] else 'blocked'}" + (f" — {args.output}" if args.output else ""))
        if not report["ok"]:
            issues = (report.get("issues", []) + report.get("content", {}).get("issues", [])
                      + report.get("package", {}).get("findings", []))
            for issue in issues[:max(1, args.max_items or 8)]:
                print(f"  {issue.get('code', 'error')}: {issue.get('message', issue.get('detail', 'see report'))}")
    return 0 if report["ok"] else 2


def run_namespace(args: argparse.Namespace, kind: str) -> int:
    argv = []
    for name in ("pptx", "slide_spec", "output", "asset_manifest", "notes", "pdf", "deliverables"):
        value = getattr(args, name, None)
        if value is not None:
            argv.extend(["--" + name.replace("_", "-"), str(value)])
    if getattr(args, "json", False):
        argv.append("--json")
    for preview in getattr(args, "preview", []) or []:
        argv.extend(["--preview", str(preview)])
    return main(kind, argv)


if __name__ == "__main__":
    sys.exit(main())
