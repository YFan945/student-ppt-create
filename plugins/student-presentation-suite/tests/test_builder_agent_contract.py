from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class BuilderAgentContractTests(unittest.TestCase):
    def read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_builder_agent_is_isolated_page_worker(self) -> None:
        text = self.read("agents/presentation-builder.md")
        frontmatter = yaml.safe_load(text.split("---", 2)[1])
        self.assertEqual("presentation-builder", frontmatter["name"])
        tools = str(frontmatter.get("tools") or "")
        for tool in ("Read", "Edit", "Write", "Bash"):
            self.assertIn(tool, tools)
        self.assertNotIn("WebSearch", tools)
        self.assertNotIn("WebFetch", tools)
        self.assertIn("Never run `ppt_pipeline.py build`", text)
        self.assertIn("Never call `run_with_pptxgenjs.js` directly", text)
        self.assertIn("BUILDER_DONE", text)
        self.assertIn("BUILDER_BLOCKED", text)
        self.assertIn("student-presentation-suite-scaffold", text)

    def test_machine_contract_routes_generation_and_repair_to_builder(self) -> None:
        contract = json.loads(self.read("references/pipeline-contract.json"))
        self.assertTrue(contract["repeat_policy"]["page_generation_requires_isolated_builder"])
        build = "\n".join(contract["stage_contracts"]["build"])
        repair = "\n".join(contract["stage_contracts"]["repair"])
        self.assertIn("student-presentation-suite:presentation-builder", build)
        self.assertIn("must not implement page modules itself", build)
        self.assertIn("student-presentation-suite:presentation-builder", repair)
        self.assertIn("mode=repair", repair)

    def test_sp_deck_keeps_page_source_out_of_main_context(self) -> None:
        skill = self.read("skills/sp-deck/SKILL.md")
        self.assertIn("student-presentation-suite:presentation-builder", skill)
        self.assertIn("主会话不得直接实现或修复 `pages/pNN-*.js`", skill)
        self.assertIn("不接收页面源码", skill)
        self.assertIn("mode=initial", skill)
        self.assertIn("mode=repair", skill)


if __name__ == "__main__":
    unittest.main()
