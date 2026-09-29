"""Focused regressions for the hardened research evidence pipeline."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
VALIDATE_RESEARCH = ROOT / "scripts" / "validate_research_pack.py"
COMPILE = ROOT / "scripts" / "research_pack_to_evidence.py"
VALIDATE_SPEC = ROOT / "scripts" / "validate_slide_spec.py"
GUARD = ROOT / "skills" / "sp-deck" / "scripts" / "slide_spec_guard.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_validate_research_pack import base_pack  # noqa: E402


class ResearchHardeningRegressionTests(unittest.TestCase):
    def run_python(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_compiled_slide_spec_passes_the_real_slide_spec_validator(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            pack = tmp / "research-pack.json"
            validation = tmp / "research-pack-validation.json"
            draft = tmp / "slide-spec-draft.json"
            compiled = tmp / "slide-spec-compiled.json"
            evidence_map = tmp / "evidence-map.json"
            spec_report = tmp / "slide-spec-validation.json"

            pack.write_text(json.dumps(base_pack(), ensure_ascii=False, indent=2), encoding="utf-8")
            research_result = self.run_python(
                VALIDATE_RESEARCH,
                str(pack),
                "--output",
                str(validation),
            )
            self.assertEqual(0, research_result.returncode, research_result.stdout + research_result.stderr)

            draft.write_text(
                json.dumps(
                    {
                        "schema_version": "2.0",
                        "slides": [
                            {
                                "id": 1,
                                "title": "对象幻觉仍是关键风险",
                                "layout": "content",
                                "content": "对象幻觉与基准幻觉率",
                                "evidence_refs": ["F01", "D01"],
                                "timing_sec": 45,
                                "owner": "Individual",
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            compile_result = self.run_python(
                COMPILE,
                str(pack),
                "--validation-report",
                str(validation),
                "--slide-spec",
                str(draft),
                "--compiled-slide-spec",
                str(compiled),
                "--output",
                str(evidence_map),
            )
            self.assertEqual(0, compile_result.returncode, compile_result.stdout + compile_result.stderr)

            spec_result = self.run_python(
                VALIDATE_SPEC,
                str(compiled),
                "--output",
                str(spec_report),
                "--json",
            )
            self.assertEqual(0, spec_result.returncode, spec_result.stdout + spec_result.stderr)
            report = json.loads(spec_report.read_text(encoding="utf-8"))
            self.assertTrue(report["valid"], report["errors"])

            spec = json.loads(compiled.read_text(encoding="utf-8"))
            self.assertEqual(["E01", "E02"], spec["slides"][0]["evidence_refs"])
            self.assertEqual([1], spec["evidence_ledger"][0]["used_on_slides"])
            self.assertEqual(["S01", "S02"], spec["evidence_ledger"][0]["source_ids"])

    def test_legacy_v10_lock_remains_readable_after_upgrade(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            spec = tmp / "slide-spec.json"
            validation = tmp / "slide-spec-validation.json"
            lock = tmp / "slide-spec-lock.json"

            spec.write_text(
                json.dumps(
                    {
                        "slides": [
                            {
                                "id": 1,
                                "title": "Legacy",
                                "layout": "content",
                                "content": "legacy",
                                "timing_sec": 30,
                                "owner": "Individual",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            spec_hash = hashlib.sha256(spec.read_bytes()).hexdigest()
            validation.write_text(
                json.dumps({"valid": True, "slide_spec_sha256": spec_hash}),
                encoding="utf-8",
            )
            validation_hash = hashlib.sha256(validation.read_bytes()).hexdigest()
            lock.write_text(
                json.dumps(
                    {
                        "lock_version": "1.0",
                        "status": "frozen",
                        "revision": 1,
                        "reason": "legacy",
                        "parent_slide_spec_sha256": None,
                        "slide_spec": str(spec.resolve()),
                        "slide_spec_sha256": spec_hash,
                        "validation_report": str(validation.resolve()),
                        "validation_report_sha256": validation_hash,
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_python(GUARD, "check", "--lock-file", str(lock), "--json")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"], payload["errors"])


class RetrievalMechanicsContractTests(unittest.TestCase):
    """2026-09-29: a dead search backend turned the research phase into a SERP crawl.

    The researcher spent 1176 of its 1256 retrieval seconds fetching search-result
    pages (81 of 135 fetches, median 8.5 s) after `No links found` came back for 30
    of 31 searches. The first cut over-fitted that outage — it told the executor to
    issue searches one per turn and to abandon re-phrasing — which would have taxed
    every later healthy run. What is pinned here is the corrected doctrine: result
    pages are not sources (an evidence rule, environment-independent), search batches
    stay small rather than serial, and a backend that returned nothing is recorded as
    `search_unavailable` instead of being read as "no evidence exists".
    """

    AGENT = ROOT / "agents" / "presentation-researcher.md"
    WORKFLOW = ROOT / "references" / "research-workflow.md"
    SPAWN = ROOT / "references" / "spawn-templates.md"
    COST = ROOT / "references" / "cost-discipline.md"
    SKILL = ROOT / "skills" / "sp-research" / "SKILL.md"
    SCHEMA = ROOT / "references" / "research-pack.schema.json"

    def read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def test_searches_are_not_serialized_by_instruction(self) -> None:
        agent = self.read(self.AGENT)
        self.assertIn("Batch independent calls into one turn", agent)
        self.assertNotIn("Issue searches", agent, "serializing searches costs a turn each")
        self.assertIn("keep search batches", agent)
        self.assertIn("do not serialize them", agent)

    def test_small_batches_are_the_stated_remedy(self) -> None:
        cost = self.read(self.COST)
        self.assertIn("不是**退化成一次一条", cost)
        self.assertIn("检索批次", cost)

    def test_result_pages_are_never_sources(self) -> None:
        # The agent prompt is English, the references are Chinese: assert the rule
        # in each surface's own language, and that both name the hosts actually fetched.
        bans = {
            self.AGENT: "never a source",
            self.WORKFLOW: "结果页永远不是来源",
            self.SPAWN: "永远不是来源",
        }
        for path, phrase in bans.items():
            text = self.read(path)
            with self.subTest(path=path.name):
                self.assertIn(phrase, text)
                self.assertTrue(
                    "so.com" in text and "duckduckgo" in text,
                    "the rule must name the hosts that were actually fetched",
                )

    def test_backend_failure_has_its_own_reason(self) -> None:
        schema = json.loads(self.read(self.SCHEMA))
        reasons = schema["properties"]["unresolved"]["items"]["properties"]["reason"]["enum"]
        self.assertIn("search_unavailable", reasons)
        self.assertNotIn("out_of_budget", reasons, "budget vocabulary is retired")
        for path in (self.AGENT, self.WORKFLOW, self.SPAWN, self.SKILL):
            with self.subTest(path=path.name):
                self.assertIn("search_unavailable", self.read(path))

    def test_the_deterministic_route_is_documented_where_the_executor_reads(self) -> None:
        for path in (self.AGENT, self.WORKFLOW, self.SPAWN, self.SKILL):
            text = self.read(path)
            with self.subTest(path=path.name):
                self.assertIn("fetch-text", text)
                self.assertIn("--scope", text)
        agent = self.read(self.AGENT)
        self.assertIn("text_sha256", agent, "the quote must be bound to the fetched artifact")
        self.assertIn("not with a summarizing reader", agent)

    def test_a_dead_backend_is_not_read_as_absent_evidence(self) -> None:
        agent = self.read(self.AGENT)
        self.assertIn("not** evidence that the\n     claim is unsupportable", agent)
        self.assertIn("Direct-source route", agent)
        self.assertIn("verbatim", agent)
        self.assertIn("主源直取", self.read(self.WORKFLOW))
        self.assertNotIn("停止换词重搜", self.read(self.WORKFLOW))


if __name__ == "__main__":
    unittest.main()
