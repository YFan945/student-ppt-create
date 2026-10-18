from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_helpers import load_module

ROOT = Path(__file__).resolve().parents[1]
runtime = load_module(ROOT / "scripts/runtime_evidence.py")


class RuntimeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.work = self.project / "outputs/.pptx-work/test"
        self.work.mkdir(parents=True)
        env = patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.project)})
        env.start()
        self.addCleanup(env.stop)
        self.event = {
            "cwd": str(self.project),
            "session_id": "parent",
            "agent_id": "child",
            "agent_type": runtime.RESEARCHER,
        }

    def event_call(self, event, **extra):
        return runtime.handle({**self.event, "hook_event_name": event, **extra})

    def test_research_receipt_ledger_counts_retrieval_calls(self):
        self.event["agent_type"] = runtime.RESEARCHER
        self.event_call("SubagentStart")
        self.event_call("PostToolUse", tool_name="WebSearch")
        self.event_call("PostToolUse", tool_name="WebFetch")
        self.event_call("PostToolUse", tool_name="WebFetch")
        ledger = self.project / "outputs/.pptx-work/.guard/agent-parent-child.json"
        counts = json.loads(ledger.read_text(encoding="utf-8"))["retrieval"]
        self.assertEqual({"WebSearch": 1, "WebFetch": 2}, counts)

    def test_prose_search_is_advisory_and_a_record_is_usable(self) -> None:
        self.event["agent_type"] = runtime.RESEARCHER
        prose = "我会为您搜索。根据已知知识，风电利用小时为2221。"
        self.event_call(
            "PostToolUse",
            tool_name="WebSearch",
            tool_input={"query": "风电利用小时"},
            tool_response=prose,
        )
        denied = self.event_call("PreToolUse", tool_name="WebSearch", tool_input={"query": "另一条"})
        self.assertEqual(0, denied)
        records = '[{"title": "统计", "link": "https://www.nea.gov.cn/2025/a.htm", "content": "1"}]'
        self.event_call(
            "PostToolUse",
            tool_name="WebSearch",
            tool_input={"query": "装机"},
            tool_response=records,
        )
        allowed = self.event_call("PreToolUse", tool_name="WebSearch", tool_input={"query": "再一条"})
        self.assertEqual(0, allowed)

    def test_a_bare_empty_result_does_not_close_search(self) -> None:
        self.event["agent_type"] = runtime.RESEARCHER
        self.event_call(
            "PostToolUse",
            tool_name="WebSearch",
            tool_input={"query": "冷门措辞"},
            tool_response="Links:\n- No links found.",
        )
        self.assertEqual(
            0, self.event_call("PreToolUse", tool_name="WebSearch", tool_input={"query": "另一条"})
        )

    def test_structured_tool_response_is_preserved_and_runtime_failure_is_explicit(self) -> None:
        self.event["agent_type"] = runtime.RESEARCHER
        self.event_call("PostToolUse", tool_name="WebSearch", tool_input={"query": "报告"},
                        tool_response={"content": [{"type": "text", "text": '[{"title":"Report","snippet":"Text","url":"https://example.org/report"}]'}]})
        self.assertEqual(0, self.event_call("PreToolUse", tool_name="WebSearch", tool_input={"query": "另一条"}))
        self.event_call("PostToolUse", tool_name="WebSearch", tool_input={"query": "报告"},
                        tool_response={"execution_status": "not_executed", "text": "failed"})
        self.assertEqual(2, self.event_call("PreToolUse", tool_name="WebSearch", tool_input={"query": "另一条"}))

    def test_large_json_response_is_not_truncated_into_an_unknown_payload(self) -> None:
        self.event["agent_type"] = runtime.RESEARCHER
        response = json.dumps({"results": [{"title": "报告", "snippet": "x" * 22000, "link": "https://example.org/report"}]})
        self.event_call("PostToolUse", tool_name="WebSearch", tool_input={"query": "报告"}, tool_response=response)
        self.assertEqual(0, self.event_call("PreToolUse", tool_name="WebSearch", tool_input={"query": "另一条"}))

    def test_body_reads_and_content_searches_require_positive_limits(self) -> None:
        self._close_search()
        for limit in (0, -1, True, "40"):
            with self.subTest(limit=limit):
                self.assertEqual(2, self.event_call("PreToolUse", tool_name="Read", tool_input={"file_path": "E:/work/research/fetched/content.txt", "limit": limit}))
                self.assertEqual(2, self.event_call("PreToolUse", tool_name="Grep", tool_input={"path": "E:/work/research/fetched", "pattern": "year", "output_mode": "content", "head_limit": limit}))

    def test_zcode_prefixed_researcher_is_the_same_channel(self) -> None:
        self.event["agent_type"] = "zcode-student-presentation-suite:presentation-researcher"
        self.event_call(
            "PostToolUse",
            tool_name="WebSearch",
            tool_input={"query": "储能"},
            tool_response="I will perform a web search and summarize from my training data: 100GW.",
        )
        self.assertEqual(0, self.event_call("PreToolUse", tool_name="WebSearch", tool_input={"query": "x"}))

    def test_webfetch_of_a_search_page_is_refused_and_a_document_is_not(self) -> None:
        self.event["agent_type"] = runtime.RESEARCHER
        self.assertEqual(
            2,
            self.event_call(
                "PreToolUse",
                tool_name="WebFetch",
                tool_input={"url": "https://cn.bing.com/search?q=gwec"},
            ),
        )
        self.assertEqual(
            0,
            self.event_call(
                "PreToolUse",
                tool_name="WebFetch",
                tool_input={"url": "https://www.gov.cn/zhengce/2021-10/26/content_5644989.htm"},
            ),
        )

    def test_printing_a_fetched_body_is_refused_and_fetch_text_is_not(self) -> None:
        self.event["agent_type"] = runtime.RESEARCHER
        dumped = (
            'grep -oE ".{20}12亿千瓦.{20}" '
            '"E:/Daima_Codes/12/outputs/.pptx-work/deck/research/fetched/u1/content.txt"'
        )
        self.assertEqual(2, self.event_call("PreToolUse", tool_name="Bash", tool_input={"command": dumped}))
        fetch = (
            'python pptx_tool.py fetch-text --scope A --out-dir '
            '"E:/work/research/fetched" --url https://www.gov.cn/a.htm'
        )
        self.assertEqual(0, self.event_call("PreToolUse", tool_name="Bash", tool_input={"command": fetch}))

    def _close_search(self) -> None:
        self.event["agent_type"] = runtime.RESEARCHER
        self.event_call(
            "PostToolUse",
            tool_name="WebSearch",
            tool_input={"query": "风电利用小时"},
            tool_response={"execution_status": "not_executed", "text": "failed"},
        )

    def test_a_closed_channel_keeps_document_fetch_bounded_read_and_pack_writes(self) -> None:
        self._close_search()
        document = (
            "python pptx_tool.py fetch-text --scope A --out-dir "
            '"E:/work/research/fetched" --url https://www.gov.cn/zhengce/2021-10/26/content_5644989.htm'
        )
        self.assertEqual(0, self.event_call("PreToolUse", tool_name="Bash", tool_input={"command": document}))
        pdf = (
            "python pptx_tool.py fetch-text --scope A --out-dir "
            '"E:/work/research/fetched" --url https://www.irena.org/media/Files/IRENA/Agency/Publication/2026/x.pdf'
        )
        self.assertEqual(0, self.event_call("PreToolUse", tool_name="PowerShell", tool_input={"command": pdf}))
        body = "E:/work/research/fetched/u1/content.txt"
        self.assertEqual(
            0,
            self.event_call("PreToolUse", tool_name="Read", tool_input={"file_path": body, "offset": 1, "limit": 40}),
        )
        report = "E:/work/research/fetched/fetch-text-report.json"
        self.assertEqual(0, self.event_call("PreToolUse", tool_name="Read", tool_input={"file_path": report}))
        pack = "python -c \"open(r'E:/work/research/research-pack.json','w').write('{}')\""
        self.assertEqual(0, self.event_call("PreToolUse", tool_name="Bash", tool_input={"command": pack}))
        validation = "python validate_research_pack.py --pack E:/work/research/research-pack.json"
        self.assertEqual(0, self.event_call("PreToolUse", tool_name="Bash", tool_input={"command": validation}))

    def test_a_paused_search_does_not_disable_evidence_tools(self) -> None:
        self._close_search()
        calls = [
            ("WebFetch", {"url": "https://example.org/news/2026/report"}),
            ("Bash", {"command": "python pptx_tool.py fetch-text --scope A --url https://example.org/news"}),
            ("Grep", {"path": "E:/work/research/fetched", "pattern": "千瓦", "output_mode": "content", "head_limit": 20}),
            ("Grep", {"path": "E:/work/research/fetched", "pattern": "千瓦", "output_mode": "files_with_matches"}),
            ("Bash", {"command": "ls E:/work"}),
        ]
        for tool, inputs in calls:
            with self.subTest(tool=tool):
                self.assertEqual(0, self.event_call("PreToolUse", tool_name=tool, tool_input=inputs))
        self.assertEqual(2, self.event_call("PreToolUse", tool_name="Read", tool_input={"file_path": "E:/work/research/fetched/content.txt"}))
        self.assertEqual(0, self.event_call("PreToolUse", tool_name="Grep", tool_input={"path": "E:/work/research/fetched", "pattern": "千瓦", "output_mode": "content"}))
        self.assertEqual(2, self.event_call("PreToolUse", tool_name="Bash", tool_input={"command": "python reset_research_channel.py"}))

    def test_an_open_channel_still_allows_a_document_webfetch_and_a_listing_fetch(self) -> None:
        self.event["agent_type"] = runtime.RESEARCHER
        self.assertEqual(
            0,
            self.event_call(
                "PreToolUse",
                tool_name="WebFetch",
                tool_input={"url": "https://www.gov.cn/zhengce/2021-10/26/content_5644989.htm"},
            ),
        )
        listing = (
            "python pptx_tool.py fetch-text --scope A --out-dir "
            '"E:/work/research/fetched" --url https://www.nea.gov.cn/xwdt/gnxw.htm'
        )
        self.assertEqual(0, self.event_call("PreToolUse", tool_name="Bash", tool_input={"command": listing}))
        body = "E:/work/research/fetched/u1/content.txt"
        self.assertEqual(0, self.event_call("PreToolUse", tool_name="Read", tool_input={"file_path": body}))

    def test_search_payloads_are_hook_owned(self) -> None:
        self.event["agent_type"] = runtime.RESEARCHER
        path = self.work / "research" / "search-payloads.json"
        self.assertEqual(
            2,
            self.event_call("PreToolUse", tool_name="Write", tool_input={"file_path": str(path)}),
        )

    def test_bash_script_writes_are_receipted_via_snapshot(self):
        """2026-09-17: json.dump edits bypassed Write-tool receipts and plan refused a healthy pack."""
        work = self.project / "outputs/.pptx-work/research-job"
        work.mkdir(parents=True)
        event = {**self.event, "agent_type": runtime.RESEARCHER}

        def call(event_kind, **extra):
            return runtime.handle({**event, "hook_event_name": event_kind, **extra})

        pack = work / "research-pack.json"
        pack.write_text('{"round": 1}')
        call("SubagentStart")
        # every round-2 edit arrives through Bash python json.dump, never the Write tool
        pack.write_text('{"round": 2}')
        call("PostToolUse", tool_name="Bash", tool_input={"command": "python -c 'json.dump(...)'"})
        call("SubagentStop")
        receipt = json.loads((work / "research-execution.json").read_text())
        self.assertTrue(receipt["spawn_verified"])
        self.assertEqual(receipt["artifact"]["sha256"], runtime.digest(pack))

    def test_pre_existing_artifact_is_not_credited_without_a_change(self):
        work = self.project / "outputs/.pptx-work/research-job"
        work.mkdir(parents=True)
        event = {**self.event, "agent_type": runtime.RESEARCHER}

        def call(event_kind, **extra):
            return runtime.handle({**event, "hook_event_name": event_kind, **extra})

        pack = work / "research-pack.json"
        pack.write_text('{"round": 1}')
        call("SubagentStart")
        call("PostToolUse", tool_name="Bash", tool_input={"command": "ls"})
        call("SubagentStop")
        self.assertFalse((work / "research-execution.json").exists())

    def test_spawn_prompt_reference_resolves_ambiguous_root(self):
        """ZCode 等环境下 root/cwd 推导可能落空：提示词显式写了 .pptx-work/<id>
        时以其为准；命名了多个或零个仍拒绝（2026-09-29 live：0.21.12 下 spawn
        三连拒，离线复现同 input 却成功——root 推导的环境差异）。"""
        (self.work / "demo-a").mkdir(exist_ok=True)
        (self.work / "demo-b").mkdir(exist_ok=True)
        inputs = {
            "prompt": (
                "work-dir（绝对路径）：E:\\proj\\outputs\\.pptx-work\\demo-a\n只研究 demo-a。"
            ),
            "description": "demo-a 检索",
            "subagent_type": runtime.RESEARCHER,
        }
        result = runtime._agent_work_dir(inputs, self.work)
        self.assertIsNotNone(result)
        self.assertEqual("demo-a", result.name)
        inputs.pop("prompt")
        self.assertIsNone(runtime._agent_work_dir(inputs, self.work))

    def test_pipeline_bash_records_work_id_without_any_spawn(self):
        """A researcher-less deck (D import / scope-C) still owns its work-id."""
        self.event["agent_type"] = "main"
        code = self.event_call(
            "PostToolUse",
            tool_name="Bash",
            tool_input={
                "command": (
                    'python "E:/plugin/scripts/ppt_pipeline.py" plan '
                    f'--work-dir "{self.work}"'
                )
            },
        )
        self.assertEqual(0, code)
        active = runtime.pipeline_context.research_active_path(self.project, "parent")
        data = json.loads(active.read_text(encoding="utf-8"))
        self.assertEqual(data.get("work_ids"), [self.work.name])

    def test_pipeline_text_mention_does_not_arm_scope(self):
        """2026-09-28: a maintenance command that merely mentions the pipeline
        (grep / git diff over the plugin source) must not arm research scope —
        it once blocked same-turn WebSearch in the plugin's own repository
        because an unrelated stale work dir sat unfinished."""
        self.event["agent_type"] = "main"
        code = self.event_call(
            "PostToolUse",
            tool_name="Bash",
            tool_input={
                "command": 'grep -rn "ppt_pipeline.py plan --work-dir" references/ README.md'
            },
        )
        self.assertEqual(0, code)
        active = runtime.pipeline_context.research_active_path(self.project, "parent")
        self.assertFalse(active.exists())

    def test_research_scope_blocks_parent_web_but_not_unrelated_sessions(self):
        base = {"cwd": str(self.project), "session_id": "parent", "hook_event_name": "PreToolUse"}
        self.assertEqual(runtime.handle({**base, "tool_name": "WebSearch"}), 0)
        runtime.handle(
            {
                **base,
                "tool_name": "Skill",
                "tool_input": {"skill": "student-presentation-suite:sp-research"},
            }
        )
        self.assertEqual(runtime.handle({**base, "tool_name": "WebSearch"}), 2)
        self.assertEqual(
            runtime.handle(
                {
                    **base,
                    "tool_name": "WebSearch",
                    "agent_type": runtime.RESEARCHER,
                    "agent_id": "research-child",
                }
            ),
            0,
        )
        self.assertEqual(
            runtime.handle({**base, "tool_name": "WebSearch", "session_id": "unrelated"}), 0
        )

    def test_stop_clears_main_session_research_scope(self):
        base = {"cwd": str(self.project), "session_id": "parent"}
        self.assertEqual(
            runtime.handle(
                {
                    **base,
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Skill",
                    "tool_input": {"skill": "student-presentation-suite:sp-deck"},
                }
            ),
            0,
        )
        self.assertEqual(
            runtime.handle({**base, "hook_event_name": "PreToolUse", "tool_name": "WebSearch"}), 2
        )
        active = self.project / "outputs/.pptx-work/.guard/research-active-parent.json"
        self.assertTrue(active.is_file())
        self.assertEqual(runtime.handle({**base, "hook_event_name": "Stop"}), 0)
        self.assertFalse(active.exists())
        self.assertEqual(
            runtime.handle({**base, "hook_event_name": "PreToolUse", "tool_name": "WebSearch"}), 0
        )

    def test_named_evidence_agent_spawn_is_blocked(self):
        base = {"cwd": str(self.project), "session_id": "parent", "hook_event_name": "PreToolUse"}
        valid_input = {"subagent_type": runtime.RESEARCHER}
        rc = runtime.handle(
            {
                **base,
                "tool_name": "Agent",
                "tool_input": {**valid_input, "name": "named-researcher"},
            }
        )
        self.assertEqual(2, rc)
        rc = runtime.handle({**base, "tool_name": "Agent", "tool_input": valid_input})
        self.assertEqual(0, rc)

    def test_nested_evidence_agent_spawn_is_blocked(self):
        base = {
            "cwd": str(self.project),
            "session_id": "parent",
            "hook_event_name": "PreToolUse",
            "agent_id": "outer-teammate",
            "tool_name": "Agent",
            "tool_input": {"subagent_type": runtime.RESEARCHER},
        }
        self.assertEqual(2, runtime.handle(base))

    def test_sp_deck_skill_arms_websearch_block_for_the_main_session(self):
        base = {"cwd": str(self.project), "session_id": "deck", "hook_event_name": "PreToolUse"}
        self.assertEqual(runtime.handle({**base, "tool_name": "WebSearch"}), 0)
        runtime.handle(
            {
                **base,
                "tool_name": "Skill",
                "tool_input": {"skill": "student-presentation-suite:sp-deck"},
            }
        )
        self.assertEqual(runtime.handle({**base, "tool_name": "WebSearch"}), 2)
        self.assertEqual(
            runtime.handle(
                {
                    **base,
                    "tool_name": "WebSearch",
                    "agent_type": runtime.RESEARCHER,
                    "agent_id": "research-child",
                }
            ),
            0,
        )

    def test_windows_delete_pending_open_is_retried_not_raised(self):
        """Windows delete-pending: after unlink, exists() reports False while open()
        still raises PermissionError until every handle closes. 2026-09-18 CI: the
        8-thread parallel-read test hit exactly this and the old
        `if not path.exists(): raise` turned a routine collision into a failure."""
        original_open = os.open
        calls = 0

        def pending_open(path, flags, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise PermissionError(13, "delete pending", str(path))
            return original_open(path, flags, *args, **kwargs)

        with patch.object(runtime.os, "open", side_effect=pending_open), patch.object(
            runtime.time, "sleep", return_value=None
        ):
            with runtime.event_lock(self.event):
                pass
        self.assertGreaterEqual(calls, 2)

    def test_fileexists_collision_can_disappear_before_retry(self):
        original_open = os.open
        calls = 0

        def racing_open(path, flags, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise FileExistsError(17, "simulated disappearing lock", str(path))
            return original_open(path, flags, *args, **kwargs)

        with patch.object(runtime.os, "open", side_effect=racing_open), patch.object(
            runtime.time, "sleep", return_value=None
        ):
            with runtime.event_lock(self.event):
                pass
        self.assertGreaterEqual(calls, 2)

    def test_event_lock_recovers_abandoned_stale_lock(self):
        guard = self.project / "outputs/.pptx-work/.guard"
        guard.mkdir(parents=True, exist_ok=True)
        lock = guard / "lock-parent-child"
        lock.write_text('{"pid": 999999}')
        stale = time.time() - runtime.LOCK_STALE_SECONDS - 5
        os.utime(lock, (stale, stale))
        with runtime.event_lock(self.event):
            self.assertTrue(lock.is_file())
            payload = json.loads(lock.read_text())
            self.assertEqual(payload["pid"], os.getpid())
        self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()

class ResearchActiveReleaseTests(unittest.TestCase):
    """2026-09-20 review: scope release must be deterministic at delivery.

    research-active cleared only at Stop or by TTL, so a session that finished
    its deck kept blocking main-session WebSearch. complete now releases it —
    as soon as EVERY work-dir is complete; any other state keeps it armed.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        env = patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.project)})
        env.start()
        self.addCleanup(env.stop)

    def main_search(self):
        return runtime.handle({
            "cwd": str(self.project),
            "session_id": "parent",
            "hook_event_name": "PreToolUse",
            "tool_name": "WebSearch",
            "tool_input": {"query": "latest battery prices"},
        })

    def write_manifest(self, work_id: str, state: str) -> None:
        work = self.project / "outputs/.pptx-work" / work_id
        work.mkdir(parents=True, exist_ok=True)
        (work / "build-manifest.json").write_text(json.dumps({"state": state}), encoding="utf-8")

    def test_release_after_all_work_ids_complete(self):
        runtime.pipeline_context.mark_research_active(self.project, {"session_id": "parent"})
        self.write_manifest("deck-a", "complete")
        self.write_manifest("deck-b", "complete")
        self.assertEqual(self.main_search(), 0)
        self.assertFalse(
            (self.project / "outputs/.pptx-work/.guard/research-active-parent.json").exists()
        )

    def test_kept_armed_while_any_work_id_is_in_production(self):
        runtime.pipeline_context.mark_research_active(self.project, {"session_id": "parent"})
        self.write_manifest("deck-a", "complete")
        self.write_manifest("deck-b", "qa")
        self.assertEqual(self.main_search(), 2)

    def researcher_spawn_records_work_id(self):
        """A researcher spawn whose prompt names one work-dir records it (same
        single-path detection as the Agent spawn guard)."""
        work = self.project / "outputs/.pptx-work/test"
        work.mkdir(parents=True, exist_ok=True)
        prompt = f"work-dir (only write location): {work.resolve()}"
        rc = runtime.handle({
            "cwd": str(self.project),
            "session_id": "parent",
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "tool_input": {"subagent_type": runtime.RESEARCHER, "prompt": prompt},
        })
        assert rc == 0, rc
        active = runtime.pipeline_context.research_active_path(self.project, "parent")
        data = json.loads(active.read_text(encoding="utf-8"))
        assert data.get("work_ids") == ["test"], data

    def test_release_scoped_to_session_work_ids_ignores_stale_decks(self):
        """2026-09-20 review: a session that finished deck `test` must release
        even when an unrelated historical deck sits in `incomplete`."""
        self.researcher_spawn_records_work_id()
        self.write_manifest("test", "complete")
        self.write_manifest("deck-002-stale", "incomplete")
        self.write_manifest("deck-003", "complete")
        self.assertEqual(self.main_search(), 0)
        self.assertFalse(
            (self.project / "outputs/.pptx-work/.guard/research-active-parent.json").exists()
        )

    def test_kept_armed_while_recorded_work_id_still_in_production(self):
        self.researcher_spawn_records_work_id()
        self.write_manifest("test", "qa")
        self.write_manifest("deck-other", "complete")
        self.assertEqual(self.main_search(), 2)

    def test_research_active_releases_at_complete_for_all_consumers(self):
        """2026-09-20 review: the release lives inside research_active, so
        every consumer (WebSearch refusal, named-teammate guard) also sees a
        delivered deck as inactive — not just the WebSearch path."""
        runtime.pipeline_context.mark_research_active(self.project, {"session_id": "parent"})
        self.write_manifest("test", "complete")
        self.assertTrue(
            runtime.pipeline_context.research_active(self.project, {"session_id": "parent"})
            is False
        )
        self.assertFalse(
            (self.project / "outputs/.pptx-work/.guard/research-active-parent.json").exists()
        )

    def test_kept_armed_when_no_manifest_or_unreadable(self):
        runtime.pipeline_context.mark_research_active(self.project, {"session_id": "parent"})
        (self.project / "outputs/.pptx-work/intake-only").mkdir(parents=True)
        self.assertEqual(self.main_search(), 2)
        self.write_manifest("intake-only", "complete")
        (self.project / "outputs/.pptx-work/broken/build-manifest.json").parent.mkdir(parents=True)
        (self.project / "outputs/.pptx-work/broken/build-manifest.json").write_text("{oops", encoding="utf-8")
        self.assertEqual(self.main_search(), 2)


if __name__ == "__main__":
    unittest.main()
