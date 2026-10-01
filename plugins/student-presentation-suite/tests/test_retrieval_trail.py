"""The two channel verdicts a run needs to stop instead of looping (2026-09-30 live).

A researcher spent 28 minutes and 78K output tokens after its search layer died: the
search backend never executed (19 of 19 searches returned the wrapper model's own
prose, one of them literally claiming it had no web search tool), and a publisher's
record endpoint answered ten differently-parameterised requests with one byte-identical
97-byte body while the executor varied `t=` five times, one full model turn each. Both
were invisible to the trail — so both are computed here, from data the trail already
carries, and the reaction is a *classification* ("this channel is closed") rather than a
counter ("you may try three more times").

What is pinned: distinct requests sharing one body is the degenerate signature and a
repeat of one URL is not; the marker set that distinguishes "the backend never ran" from
"the index has no coverage"; and that both verdicts are named in the contract the
executor actually reads.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.retrieval_trail import (  # noqa: E402
    DEGENERATE_ECHO,
    INDEX_EMPTY,
    SEARCH_BACKEND_NOT_EXECUTED,
    degenerate_channels,
    endpoint_key,
    is_listing_locator,
    is_locator,
    search_backend_never_executed,
    search_channel_closed,
    search_payload_signature,
)

WORKFLOW = ROOT / "references" / "research-workflow.md"
AGENT = ROOT / "agents" / "presentation-researcher.md"
SPAWN = ROOT / "references" / "spawn-templates.md"
SKILL = ROOT / "skills" / "sp-research" / "SKILL.md"

# The body the live endpoint returned for every parameter combination that missed.
SHELL = '{"code":200,"msg":"操作成功","data":null,"paramsVO":{"q":"风电光伏","t":"zhengcelibrary_bm"}}'


def record(url: str, digest: str, *, ok: bool = True) -> dict:
    return {"url": url, "raw_sha256": digest, "ok": ok, "host_class": "public"}


class EndpointKeyTests(unittest.TestCase):
    def test_query_and_fragment_are_not_part_of_the_channel(self) -> None:
        """One endpoint, many parameters: the parameters are not a second channel."""
        self.assertEqual(
            "https://sousuo.www.gov.cn/search-gov/data",
            endpoint_key("https://sousuo.www.gov.cn/search-gov/data?t=govall&q=x#frag"),
        )

    def test_different_paths_on_one_host_are_different_channels(self) -> None:
        self.assertNotEqual(
            endpoint_key("https://www.nea.gov.cn/xwfb/index.htm"),
            endpoint_key("https://www.nea.gov.cn/news/jwzdt.htm"),
        )

    def test_a_url_without_a_host_has_no_channel(self) -> None:
        """`file:` and friends never reach the network, so they cannot be judged."""
        self.assertEqual("", endpoint_key("file:///C:/tmp/x.txt"))


class DegenerateChannelTests(unittest.TestCase):
    def test_distinct_requests_sharing_one_body_are_flagged(self) -> None:
        records = [
            record(f"https://sousuo.www.gov.cn/search-gov/data?t={t}&q=q{i}", "shell")
            for i, t in enumerate(("govall", "zhengcelibrary_gw", "zhengcelibrary_cp", "news"))
        ]
        found = degenerate_channels(records)
        self.assertEqual(1, len(found), found)
        self.assertEqual(DEGENERATE_ECHO, found[0]["verdict"])
        self.assertEqual("https://sousuo.www.gov.cn/search-gov/data", found[0]["channel"])
        self.assertEqual(4, found[0]["distinct_requests"])

    def test_a_verdict_names_the_channel_not_the_requests(self) -> None:
        """Per channel, so nobody reads it as a tally of attempts."""
        records = [
            record(f"https://sousuo.www.gov.cn/search-gov/data?t={t}", "shell") for t in ("a", "b")
        ]
        found = degenerate_channels(records)
        self.assertEqual(["channel", "distinct_requests", "raw_sha256", "urls", "verdict"], sorted(found[0]))

    def test_repeating_one_url_is_never_degenerate(self) -> None:
        """Identical bytes are what a repeat is *supposed* to produce."""
        url = "https://www.nea.gov.cn/2025/page.html"
        self.assertEqual([], degenerate_channels([record(url, "same"), record(url, "same")]))

    def test_a_real_result_alongside_the_shell_is_not_flagged(self) -> None:
        """The live endpoint answered `t=zhengcelibrary_bm` with 18–24K characters of
        real records, so the channel is degenerate *for some requests*, not broken —
        which is exactly why the verdict is per (channel, body), not per host."""
        records = [
            record(f"https://sousuo.www.gov.cn/search-gov/data?t={t}", "shell")
            for t in ("govall", "news")
        ] + [record("https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_bm&q=x", "real")]
        found = degenerate_channels(records)
        self.assertEqual(1, len(found))
        self.assertEqual(
            [
                "https://sousuo.www.gov.cn/search-gov/data?t=govall",
                "https://sousuo.www.gov.cn/search-gov/data?t=news",
            ],
            found[0]["urls"],
        )
        self.assertEqual("shell", found[0]["raw_sha256"])

    def test_one_request_alone_is_never_a_verdict(self) -> None:
        self.assertEqual([], degenerate_channels([record("https://example.org/a?q=1", "shell")]))

    def test_failed_and_unhashed_records_are_ignored(self) -> None:
        records = [
            record("https://example.org/a?q=1", "shell", ok=False),
            record("https://example.org/a?q=2", "shell", ok=False),
            {"url": "https://example.org/a?q=3", "ok": True},
        ]
        self.assertEqual([], degenerate_channels(records))


class SearchSignatureTests(unittest.TestCase):
    def test_structured_and_readable_links_are_candidates(self) -> None:
        for payload in (
            '{"title":"Report","snippet":"Text","link":"https://example.org/report"}',
            '{"results":[{"url":"https://example.org/report","title":"Report"}]}',
        ):
            self.assertEqual("results", search_payload_signature(payload))
        for payload in (
            'The model wrote: {"title":"Invented","link":"https://example.org/fake"}',
            '[Report](https://example.org/report)',
            'An article says No links found.',
        ):
            self.assertEqual("results" if "https://" in payload else "unknown_payload", search_payload_signature(payload))

    def test_explicit_runtime_status_is_required_to_assert_non_execution(self) -> None:
        self.assertEqual(SEARCH_BACKEND_NOT_EXECUTED,
                         search_payload_signature("", execution_status="not_executed"))
        self.assertEqual("unknown_payload", search_payload_signature("I have no search tool"))

    def test_success_then_failure_pauses_and_a_documented_reset_recovers(self) -> None:
        records = {"payload": '{"title":"Report","link":"https://example.org/report"}'}
        failure = {"payload": "failed", "execution_status": "not_executed"}
        self.assertTrue(search_channel_closed([records, failure]))
        self.assertFalse(search_channel_closed([records, failure, {"event": "channel_reset"}]))

    def test_news_articles_are_documents_not_directory_pages(self) -> None:
        for path in ("/news/2026/research-results", "/press-releases/2026/annual-report", "/xwdt/report.htm"):
            self.assertFalse(is_listing_locator("https://example.org" + path))

    def test_a_faked_tool_call_means_the_backend_never_ran(self) -> None:
        """Both real payloads from the outage: the wrapper wrote the call as text."""
        for payload in (
            'Web search results for query: "x"\n\n<tool_call>\n{"name": "web_search"}\n</tool_call>\n\nLinks:\n- No links found.',
            'I don\'t have access to a web search tool in this conversation, but I can share what I know from my training data',
            '<search_tool>\n<query>Lazard LCOE 2025</query>\n</search_tool>',
            "<search>\n<query>2021年新能源上网电价</query>\n</search>",
            '```\nsearch_web("2025年 光伏发电利用率")\n```',
        ):
            with self.subTest(payload=payload[:40]):
                self.assertEqual("unknown_payload", search_payload_signature(payload))

    def test_prose_links_are_candidates_without_proving_figures(self) -> None:
        """16 of the 19 live payloads looked like hit lists and matched no marker.

        The positive signal is a backend record. A paragraph that names a figure, or even
        a URL, is the wrapper writing — classifying it as results is what sent the
        researcher off to verify invented numbers.
        """
        payload = (
            "我会为您搜索关于2025年风电平均利用小时数的信息。根据已知知识，"
            "2024年全国风电平均利用小时数为2221小时。详见 https://www.nea.gov.cn/ 。"
        )
        self.assertEqual("results", search_payload_signature(payload))

    def test_a_bare_empty_envelope_is_coverage_not_a_dead_backend(self) -> None:
        self.assertEqual(INDEX_EMPTY, search_payload_signature("Links:\n- No links found."))

    def test_an_empty_payload_is_unclassified(self) -> None:
        self.assertEqual("", search_payload_signature(""))
        self.assertEqual("", search_payload_signature("   "))

    def test_the_backends_own_records_are_results(self) -> None:
        payload = (
            'Web search results for query: "x"\n\n**web_search_prime_result_summary:** '
            '[{"title": "报告", "link": "https://www.irena.org/x", "content": "…", "refer": "ref_1"}]'
        )
        self.assertEqual("results", search_payload_signature(payload))

    def test_one_dead_search_among_live_ones_is_not_a_session_outage(self) -> None:
        """The status still says `failed`; only the signature separates them."""
        executions = [
            {"query": "a", "status": "failed", "signature": SEARCH_BACKEND_NOT_EXECUTED},
            {"query": "b", "status": "failed", "signature": "index_empty"},
        ]
        self.assertFalse(search_backend_never_executed(executions))

    def test_every_failure_being_the_same_signature_is_a_session_outage(self) -> None:
        executions = [
            {"query": f"q{n}", "status": "failed", "signature": SEARCH_BACKEND_NOT_EXECUTED}
            for n in (1, 2, 3)
        ]
        self.assertTrue(search_backend_never_executed(executions))

    def test_successes_do_not_excuse_a_dead_backend_and_do_not_invent_one(self) -> None:
        self.assertFalse(
            search_backend_never_executed([{"query": "a", "status": "ok", "signature": "results"}])
        )
        self.assertFalse(search_backend_never_executed([]))

    def test_a_log_without_signatures_never_triggers_the_verdict(self) -> None:
        """Older writers and unclassified failures stay fail-open: the audit may not
        invent an outage out of a missing field."""
        self.assertFalse(
            search_backend_never_executed(
                [{"query": "a", "status": "failed"}, {"query": "b", "status": "failed"}]
            )
        )

    def test_unknown_prose_keeps_search_available(self) -> None:
        prose = {"query": "风电", "payload": "根据已知知识，利用小时为2221。"}
        empty = {"query": "另一条", "payload": "Links:\n- No links found."}
        records = {
            "query": "容量",
            "payload": '[{"title": "报告", "link": "https://www.irena.org/x", "content": "…"}]',
        }
        self.assertFalse(search_channel_closed([prose]))
        self.assertFalse(search_channel_closed([empty]), "coverage for one phrasing is not a dead channel")
        self.assertFalse(search_channel_closed([prose, records]), "a real record re-opens the channel")
        self.assertFalse(search_channel_closed([]))


class ContractSyncTests(unittest.TestCase):
    """The verdicts are only useful if the executor's own surfaces name them."""

    def test_the_degenerate_row_and_the_channel_once_rule_are_documented(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("degenerate_channels", workflow)
        self.assertIn("同一端点对不同请求返回同一份字节", workflow)
        self.assertIn("通道按类判定一次，不按次数累加", workflow)
        self.assertIn("不是同一通道的新参数或新措辞", workflow)
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("degenerate_channels", skill)
        self.assertIn("通道按类判定一次，不按次数累加", skill)
        self.assertIn("degenerate_channel", skill)

    def test_the_backend_not_executed_signature_is_documented(self) -> None:
        self.assertIn("backend_not_executed", WORKFLOW.read_text(encoding="utf-8"))
        agent = AGENT.read_text(encoding="utf-8")
        self.assertIn("never executed", agent)
        self.assertIn("backend_not_executed", agent)
        spawn = SPAWN.read_text(encoding="utf-8")
        self.assertIn("没有执行", spawn)
        self.assertIn("backend_not_executed", spawn)
        self.assertIn("degenerate_channels", spawn)
        self.assertIn("search_backend_not_executed", SKILL.read_text(encoding="utf-8"))

    def test_the_one_out_dir_rule_is_documented_where_the_executor_reads(self) -> None:
        """The report accumulates, and a nested directory is folded back into it."""
        agent = AGENT.read_text(encoding="utf-8")
        self.assertIn("one `--out-dir`", agent)
        self.assertIn("sub-directories", agent)
        self.assertIn("channel_closed", agent)
        self.assertIn("同一个 `--out-dir`", SPAWN.read_text(encoding="utf-8"))

    def test_the_verdicts_are_classifications_not_a_budget(self) -> None:
        """Owner standing rule: the reaction retires a channel, it never caps a run.

        The one thing that must not come back is a *count* — the same verdict is stated
        as a property of the channel, so it cannot loosen as a run gets longer.
        """
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("上限是计数器，通道判定是分类", workflow)
        self.assertIn("一条通道只判一次", workflow)

    def test_listing_pages_are_locators_and_policy_pages_are_documents(self) -> None:
        self.assertTrue(is_listing_locator("https://sousuo.www.gov.cn/search-gov/data?t=all&q=x"))
        self.assertFalse(is_listing_locator("https://www.nea.gov.cn/xwdt/gnxw.htm"))
        self.assertTrue(is_listing_locator("https://www.nea.gov.cn/xwfb/index.htm"))
        self.assertTrue(is_listing_locator("https://www.gwec.net/news"))
        self.assertTrue(is_listing_locator("https://www.irena.org/press-releases"))
        self.assertTrue(is_listing_locator("https://www.example.com/index.html"))
        self.assertFalse(
            is_listing_locator("https://www.gov.cn/zhengce/2021-10/26/content_5644989.htm")
        )
        self.assertFalse(is_listing_locator("https://www.gov.cn/zhengce/news/P0202.pdf"))
        self.assertTrue(is_locator("https://cn.bing.com/search?q=x"))
        self.assertFalse(is_locator("https://www.gov.cn/zhengce/2021-10/26/content_5644989.htm"))

    def test_the_closeout_is_written_where_the_executor_and_parent_read(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("通道关闭之后", workflow)
        self.assertIn("`listing`", workflow)
        skill = SKILL.read_text(encoding="utf-8")
        self.assertIn("通道关闭之后", skill)
        self.assertIn("不再 spawn", skill)
        self.assertIn("通道关闭之后", SPAWN.read_text(encoding="utf-8"))
        self.assertIn("closed for WebSearch only", AGENT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
