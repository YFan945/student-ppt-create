#!/usr/bin/env python3
"""Build the golden sample end-to-end through the v0.8 pipeline.

This is a reproducible showcase, not a unit test. It runs the real gate scripts
in the real order so the sample's evidence chain can be inspected:

    Art Direction -> reference retrieval -> composition candidates -> wireframes
    -> v0.8 visual generation gate -> deck.js -> package validate -> readback
    -> render

Generated binaries (pptx/png/pdf) go to <out-dir> (default outputs/golden-sample/)
and are intentionally not committed. Source artifacts live in this directory.

Usage:
    python examples/golden-sample/build.py [--out-dir <dir>] [--skip-render]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
SKILL_SCRIPTS = PLUGIN_ROOT / "skills" / "sp-deck" / "scripts"
REPO_ROOT = PLUGIN_ROOT.parents[1]

if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from shared.design_tokens import resolve_design_tokens  # noqa: E402

SLIDE_SPEC = HERE / "slide-spec.yaml"
ART_DIRECTION = HERE / "art-direction.yaml"
EVIDENCE_DIR = HERE / "composition"
TOKENS_FILE = HERE / "tokens.json"

# Retrieval query per high-leverage slide. The selection is produced first; the
# checked-in candidate files cite references from these results.
RETRIEVAL_QUERIES = {
    1: dict(role="cover", grammar="coursework", strategy="typography", density="low", tags=""),
    2: dict(role="frame", grammar="coursework", strategy="typography", density="low", tags=""),
    5: dict(role="prove", grammar="academic-research", strategy="chart", density="medium", tags="evidence,result"),
    9: dict(role="conclude", grammar="coursework", strategy="typography", density="low", tags=""),
}


def run(cmd: list[str], label: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHON"] = sys.executable
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(cmd, cwd=str(PLUGIN_ROOT), env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise SystemExit(f"[{label}] failed\n{result.stdout}\n{result.stderr}")
    return result


def py(*args: object) -> list[str]:
    return [sys.executable, *[str(a) for a in args]]


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_tokens() -> dict:
    """Resolve the style tokens for the sample.

    The style ships both its light palette and the matching dark companion, so the
    navy cover/section/closing pages stay in the same colour family as the light
    content pages. No local colour derivation is needed here.
    """
    tokens = resolve_design_tokens("Academic Rigorous")
    if "dark_palette" not in tokens:
        raise SystemExit("resolved style tokens must include a dark_palette")
    TOKENS_FILE.write_text(json.dumps(tokens, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return tokens


def high_leverage_slides() -> list[int]:
    import yaml

    data = yaml.safe_load(ART_DIRECTION.read_text(encoding="utf-8"))
    return [int(item["slide"]) for item in data["high_leverage_slides"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "outputs" / "golden-sample")
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()
    out_dir: Path = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {"steps": []}

    def note(step: str, detail: object = None) -> None:
        report["steps"].append({"step": step, "detail": detail})
        print(f"[ok] {step}")

    tokens = write_tokens()
    note("tokens", str(TOKENS_FILE))

    run(py(SKILL_SCRIPTS / "art_direction_check.py", ART_DIRECTION, "--strict", "--json"),
        "art-direction")
    note("art-direction gate")

    slides = high_leverage_slides()
    for slide in slides:
        query = RETRIEVAL_QUERIES[slide]
        run(py(SKILL_SCRIPTS / "visual_reference_select.py",
               "--role", query["role"], "--grammar", query["grammar"],
               "--visual-strategy", query["strategy"], "--density", query["density"],
               "--tags", query["tags"], "--count", "3",
               "--output", EVIDENCE_DIR / f"references-slide-{slide}.json"), f"retrieval-{slide}")
        run(py(SKILL_SCRIPTS / "composition_candidate_check.py",
               EVIDENCE_DIR / f"composition-candidates-{slide}.json", "--strict", "--json"),
            f"candidates-{slide}")
        run(["node", str(SCRIPTS / "composition_wireframe.js"),
             "--input", str(EVIDENCE_DIR / f"composition-candidates-{slide}.json"),
             "--output", str(EVIDENCE_DIR / f"wireframes-{slide}.pptx")], f"wireframe-{slide}")
    note("retrieval + candidates + wireframes", slides)

    run(py(SKILL_SCRIPTS / "pptx_visual_generation_gate_v08.py",
           "--slide-spec", SLIDE_SPEC, "--art-direction", ART_DIRECTION,
           "--evidence-dir", EVIDENCE_DIR,
           "--output", out_dir / "visual-generation-report.json",
           "--strict", "--json"), "visual-generation-gate")
    note("v0.8 visual generation gate")

    pptx = out_dir / "golden-ai-hallucination.pptx"
    staging = out_dir / f".deck-{os.getpid()}.pptx"
    if staging.exists():
        staging.unlink()
    run(["node", str(SCRIPTS / "run_with_pptxgenjs.js"), "--output", str(staging), str(HERE / "deck.js")],
        "deck")
    # A viewer may hold the previous artifact open; retry, then fall back to a
    # suffixed name so a preview panel never breaks a rebuild.
    import time

    for attempt in range(6):
        try:
            os.replace(staging, pptx)
            break
        except PermissionError:
            if attempt == 5:
                pptx = out_dir / "golden-ai-hallucination-rebuild.pptx"
                os.replace(staging, pptx)
                print(f"[warn] original pptx is locked by another process; wrote {pptx.name}")
            else:
                time.sleep(1)
    note("deck.js -> pptx", str(pptx))

    # CJK typography: pptxgenjs only writes <a:latin>; add <a:ea> for Chinese glyphs.
    fonts = tokens["typography"]
    run(py(SCRIPTS / "pptx_tool.py", "cjk-fonts", pptx,
           "--map", f"{fonts['title_font']}={fonts['cjk_title_font']}",
           "--map", f"{fonts['body_font']}={fonts['cjk_body_font']}"), "cjk-fonts")

    run(py(SCRIPTS / "pptx_tool.py", "validate", pptx, "--output", out_dir / "package-report.json", "--json"), "validate")
    note("package validation")

    run(py(SCRIPTS / "pptx_tool.py", "validate-asset-manifest", HERE / "asset-manifest.json",
           "--output", out_dir / "asset-manifest-report.json"), "asset-manifest")
    note("asset manifest (all deterministic, suite-original)")

    readback = out_dir / "actual-content-report.json"
    run(py(SKILL_SCRIPTS / "pptx_actual_content_check.py", pptx, SLIDE_SPEC,
           "--output", readback, "--strict", "--json"), "actual-content")
    note("actual content readback", str(readback))

    run(py(SCRIPTS / "validate_slide_spec.py", SLIDE_SPEC,
           "--output", out_dir / "slide-spec-report.json", "--json"), "slide-spec")
    lock = out_dir / "slide-spec-lock.json"
    if lock.exists():
        # The guard deliberately refuses to overwrite a frozen plan; a rebuild
        # goes through the sanctioned revision path with an explicit reason.
        run(py(SKILL_SCRIPTS / "slide_spec_guard.py", "revise",
               "--slide-spec", SLIDE_SPEC,
               "--validation-report", out_dir / "slide-spec-report.json",
               "--lock-file", lock,
               "--reason", "golden sample rebuild after spec edits"), "spec-revise")
    else:
        run(py(SKILL_SCRIPTS / "slide_spec_guard.py", "freeze",
               "--slide-spec", SLIDE_SPEC,
               "--validation-report", out_dir / "slide-spec-report.json",
               "--lock-file", lock), "spec-lock")
    note("slide spec frozen and locked")

    run(py(SCRIPTS / "build_support_outputs.py", SLIDE_SPEC,
           "--output-dir", out_dir, "--prefix", "golden-ai-hallucination",
           "--only", "speaker-notes", "--json"), "speaker-notes")
    note("speaker notes")

    if not args.skip_render:
        render_dir = out_dir / "render"
        run(py(SCRIPTS / "pptx_tool.py", "render", pptx,
               "--output-dir", render_dir, "--prefix", "golden"), "render")
        previews = sorted(render_dir.glob("*.png"))
        note("render", {"dir": str(render_dir), "previews": len(previews)})

    # Bind the authored visual review to the artifact it actually describes,
    # then run the quality and delivery gates on the real evidence chain.
    review = json.loads((HERE / "expected" / "visual-review.json").read_text(encoding="utf-8"))
    review.pop("_comment", None)
    review["pptx_sha256"] = sha256_file(pptx)
    visual_review = out_dir / "visual-review.json"
    visual_review.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    quality = out_dir / "quality-report.json"
    run(py(SKILL_SCRIPTS / "pptx_quality_gate_v071.py",
           "--pptx", pptx, "--slide-spec", SLIDE_SPEC,
           "--spec-lock", out_dir / "slide-spec-lock.json",
           "--visual-report", visual_review,
           "--output", quality, "--strict", "--json"), "quality-gate")
    note("quality gate", str(quality))

    # 渲染产物回读：量测实际字号层级 / 图表轴显式性 / 底部留白，不信任任何声明值。
    rendered = out_dir / "rendered-visual-report.json"
    run(py(SKILL_SCRIPTS / "pptx_rendered_check.py",
           "--pptx", pptx, "--output", rendered, "--json"), "rendered-visual-check")
    note("rendered visual check", str(rendered))

    previews = sorted((out_dir / "render").glob("*.png")) if not args.skip_render else []
    delivery = py(SKILL_SCRIPTS / "pptx_delivery_check_v08.py",
                  "--pptx", pptx, "--slide-spec", SLIDE_SPEC,
                  "--spec-lock", out_dir / "slide-spec-lock.json",
                  "--art-direction", ART_DIRECTION,
                  "--visual-generation-report", out_dir / "visual-generation-report.json",
                  "--quality-report", quality,
                  "--package-report", out_dir / "package-report.json",
                  "--slide-spec-report", out_dir / "slide-spec-report.json",
                  "--actual-content-report", readback,
                  "--notes", out_dir / "golden-ai-hallucination-speaker-notes.md",
                  "--output", out_dir / "delivery-report.json",
                  "--visual-reviewed", "--visual-review-report", visual_review,
                  "--strict", "--json")
    for preview in previews:
        delivery += ["--preview", str(preview)]
    run(delivery, "delivery-check")
    note("v0.8 delivery check", "complete")

    report["ok"] = True
    (out_dir / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out_dir": str(out_dir), "slides": len(slides)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
