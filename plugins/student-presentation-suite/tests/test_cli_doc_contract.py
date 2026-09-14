"""CLI-doc contract tests: documented flags must exist in the real CLIs.

The `run_gates --qa` incident (CHANGELOG documented a flag that never existed)
is the template this file exists to prevent: every script that living docs
mention together with a `--flag` must actually accept that flag, checked
against the script's own `--help` output. Documentation is not allowed to
invent CLI surfaces, and CLIs are not allowed to drop documented ones.

Scope of "living docs": plugin READMEs, all SKILL.md files, references/*.md,
and the `## Unreleased` section of the repo CHANGELOG. Released CHANGELOG
history is frozen and therefore not scanned.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
SKILL_SCRIPTS = ROOT / "skills" / "sp-deck" / "scripts"
RESEARCH_SCRIPTS = ROOT / "scripts"

# script base name -> CLI entry. .sh wrappers share the .py corpus.
PYTHON_SCRIPTS: dict[str, Path] = {
    "run_gates.py": SKILL_SCRIPTS / "run_gates.py",
    "ppt_pipeline.py": SKILL_SCRIPTS / "ppt_pipeline.py",
    "delivery_check.py": SKILL_SCRIPTS / "delivery_check.py",
    "quality_gate.py": SKILL_SCRIPTS / "quality_gate.py",
    "slide_spec_guard.py": SKILL_SCRIPTS / "slide_spec_guard.py",
    "copy_fit_preflight.py": SKILL_SCRIPTS / "copy_fit_preflight.py",
    "pptx_rendered_check.py": SKILL_SCRIPTS / "pptx_rendered_check.py",
    "pptx_actual_content_check.py": SKILL_SCRIPTS / "pptx_actual_content_check.py",
    "pptx_quality_gate_v071.py": SKILL_SCRIPTS / "pptx_quality_gate_v071.py",
    "pptx_delivery_check_v08.py": SKILL_SCRIPTS / "pptx_delivery_check_v08.py",
    "art_direction_check.py": SKILL_SCRIPTS / "art_direction_check.py",
    "composition_candidate_check.py": SKILL_SCRIPTS / "composition_candidate_check.py",
    "pptx_visual_generation_gate_v08.py": SKILL_SCRIPTS / "pptx_visual_generation_gate_v08.py",
    "workflow_guard.py": RESEARCH_SCRIPTS / "workflow_guard.py",
    "pptx_tool.py": RESEARCH_SCRIPTS / "pptx_tool.py",
    "validate_research_pack.py": RESEARCH_SCRIPTS / "validate_research_pack.py",
    "research_pack_to_evidence.py": RESEARCH_SCRIPTS / "research_pack_to_evidence.py",
    "bump_version.py": RESEARCH_SCRIPTS / "bump_version.py",
    "session_cost.py": RESEARCH_SCRIPTS / "session_cost.py",
    "smoke_research_fork.py": RESEARCH_SCRIPTS / "smoke_research_fork.py",
    "benchmark_report.py": RESEARCH_SCRIPTS / "benchmark_report.py",
}
# JS entries: the flag must appear literally in the source (no argparse help).
JS_SCRIPTS: dict[str, Path] = {
    "run_with_pptxgenjs.js": RESEARCH_SCRIPTS / "run_with_pptxgenjs.js",
    "pptx-helpers.js": RESEARCH_SCRIPTS / "pptx-helpers.js",
}
ALIASES = {"run_gates.sh": "run_gates.py"}

FLAG_RE = re.compile(r"(?<![\w-])(--[a-z0-9][a-z0-9-]*)")
SUBCOMMAND_RE = re.compile(r"\{([a-z0-9-]+(?:,[a-z0-9-]+)+)\}")


def script_help_corpus(path: Path) -> str:
    """Top-level --help plus every subcommand's --help."""
    proc = subprocess.run(
        [sys.executable, str(path), "--help"],
        check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    corpus = proc.stdout + proc.stderr
    match = SUBCOMMAND_RE.search(corpus)
    if match:
        for sub in match.group(1).split(","):
            sub_proc = subprocess.run(
                [sys.executable, str(path), sub, "--help"],
                check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            corpus += "\n" + sub_proc.stdout + sub_proc.stderr
    return corpus


def living_doc_texts() -> dict[str, str]:
    docs: dict[str, str] = {}
    for name in ("README.md", "README-zh.md"):
        path = ROOT / name
        if path.is_file():
            docs[name] = path.read_text(encoding="utf-8")
    for path in sorted((ROOT / "skills").glob("*/SKILL.md")):
        docs[f"skills/{path.parent.name}/SKILL.md"] = path.read_text(encoding="utf-8")
    for path in sorted((ROOT / "references").glob("*.md")):
        docs[f"references/{path.name}"] = path.read_text(encoding="utf-8")
    changelog = (REPO / "CHANGELOG.md")
    if changelog.is_file():
        text = changelog.read_text(encoding="utf-8")
        match = re.search(r"^## Unreleased\n(.*?)(?=^## )", text, re.S | re.M)
        if match:
            docs["CHANGELOG.md#Unreleased"] = match.group(1)
    return docs


def documented_flags(text: str) -> list[tuple[list[str], str, int]]:
    """(scripts on the line, flag, line number) triples.

    A line may legitimately mention two scripts ("A feeds B with --x" where
    --x belongs to B), so flags are attributed to *all* scripts on the line
    and validated against the union of their corpora. An invented flag still
    matches nothing and fails.
    """
    found: list[tuple[list[str], str, int]] = []
    names = sorted(set(PYTHON_SCRIPTS) | set(JS_SCRIPTS) | set(ALIASES), key=len, reverse=True)
    lines = text.splitlines()

    def scripts_on(chunk: str) -> list[str]:
        hits = [name for name in names if name in chunk]
        return sorted({ALIASES.get(hit, hit) for hit in hits}) or ["<none>"]

    for index, line in enumerate(lines):
        if not any(name in line for name in names):
            continue
        chunk = line
        look = index
        # multi-line shell commands continue with a trailing backslash
        while chunk.rstrip().endswith("\\") and look + 1 < len(lines):
            look += 1
            chunk = lines[look]
            for flag in FLAG_RE.findall(chunk):
                found.append((scripts_on(lines[index]) + scripts_on(chunk), flag, look + 1))
        for flag in FLAG_RE.findall(line):
            found.append((scripts_on(line), flag, index + 1))
    return found


class CliDocContractTests(unittest.TestCase):
    def test_all_helps_exit_zero(self) -> None:
        for name, path in PYTHON_SCRIPTS.items():
            if not path.is_file():
                continue  # optional tool; documented-flag test skips it too
            with self.subTest(script=name):
                proc = subprocess.run(
                    [sys.executable, str(path), "--help"],
                    check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
                )
                self.assertEqual(proc.returncode, 0, proc.stderr[:300])

    def test_documented_flags_exist_in_clis(self) -> None:
        corpora: dict[str, str] = {}
        for name, path in PYTHON_SCRIPTS.items():
            if path.is_file():
                corpora[name] = script_help_corpus(path)
        js_sources = {
            name: path.read_text(encoding="utf-8")
            for name, path in JS_SCRIPTS.items() if path.is_file()
        }
        problems: list[str] = []
        for doc, text in living_doc_texts().items():
            for scripts, flag, line_no in documented_flags(text):
                if flag in {"--help", "-h"}:
                    continue
                corpora_hits = [corpora[s] for s in scripts if s in corpora]
                js_hits = [js_sources[s] for s in scripts if s in js_sources]
                if corpora_hits and any(flag in corpus for corpus in corpora_hits):
                    continue
                if js_hits and any(flag in source for source in js_hits):
                    continue
                problems.append(f"{doc}:{line_no}: {flag} accepted by none of {scripts}")
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
