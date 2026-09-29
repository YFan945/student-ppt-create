"""fetch-text: the deterministic half of the retrieval fix (2026-09-29).

The harness page reader answers a *prompt* through a small model, so a number read
through it is a paraphrase; and when search returned nothing the researcher read
search-result pages instead (81 of 135 fetches, 94% of that run's retrieval wall
clock). These tests pin the replacement: raw bytes kept, text extracted without any
model, provenance bound to both hashes, and the acquisition gates enforced by the
tool rather than by a reminder.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.pptx_runtime import fetch_text  # noqa: E402

WORKFLOW = ROOT / "references" / "research-workflow.md"
TOOL = ROOT / "scripts" / "pptx_tool.py"

GBK_PAGE = """<html><head><meta http-equiv="Content-Type" content="text/html; charset=gb2312">
<title>国家能源局：2025年全国电力工业统计数据</title>
<style>body{color:#000}</style><script>var t="x";</script></head>
<body><div class="nav">首页 | 简 | 繁</div>
<p>截至2025年底，全国风电、光伏发电装机合计达14.1亿千瓦。</p>
<p>其中光伏发电装机 &quot;12.0亿千瓦&quot; &amp; 风电6.4亿千瓦。</p>
</body></html>"""


def body_response(body: bytes, content_type: str):
    def getter(_url: str, _timeout: int):
        return 200, {"content-type": content_type}, body

    return getter


class GateTests(unittest.TestCase):
    def fetch(self, url: str, out: Path, scope: str = "A", getter=None):
        return fetch_text.fetch_one(url, out, scope=scope, getter=getter)

    def test_only_scope_a_and_b_authorize_retrieval(self) -> None:
        with TemporaryDirectory() as tmp:
            for scope in ("C", "D"):
                record = self.fetch("https://example.org/doc", Path(tmp), scope=scope)
                self.assertFalse(record["ok"])
                self.assertEqual("scope_not_authorized", record["reason"])
                self.assertIn("C = no search", record["detail"])

    def test_scope_refusal_happens_before_any_request(self) -> None:
        def getter(*_args):  # pragma: no cover - must never run
            raise AssertionError("a refused call must not reach the network")

        with TemporaryDirectory() as tmp:
            record = self.fetch("https://example.org/doc", Path(tmp), scope="D", getter=getter)
            self.assertEqual("scope_not_authorized", record["reason"])

    def test_non_http_schemes_are_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            for url in ("file:///C:/Windows/win.ini", "ftp://example.org/x"):
                record = self.fetch(url, Path(tmp))
                self.assertEqual("scheme_not_allowed", record["reason"])

    def test_loopback_and_private_hosts_are_refused(self) -> None:
        with TemporaryDirectory() as tmp:
            for url in ("http://127.0.0.1/x", "http://10.0.0.5/x", "http://localhost:8080/x"):
                record = self.fetch(url, Path(tmp))
                self.assertEqual("private_host", record["reason"])

    def test_search_result_pages_are_refused_with_an_actionable_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            for url in (
                "https://cn.bing.com/search?q=x",
                "https://www.so.com/s?q=x",
                "https://www.so.com/link?m=abc",
                "https://lite.duckduckgo.com/lite/?q=x",
            ):
                record = self.fetch(url, Path(tmp))
                self.assertEqual("search_result_page", record["reason"], url)
                self.assertIn("search tool", record["detail"])

    def test_a_publisher_record_endpoint_is_not_a_search_result_page(self) -> None:
        # gov.cn's own policy-record endpoint returns document records; the workflow
        # documents it as a locator, so the tool must not refuse it.
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            record = fetch_text.fetch_one(
                "https://sousuo.www.gov.cn/search-gov/data?t=zhengce&q=%E6%8A%BD%E6%B0%B4%E8%93%84%E8%83%BD",
                out,
                scope="A",
                getter=lambda *_: (200, {"content-type": "application/json"}, b'{"data":[]}'),
            )
            self.assertNotEqual("search_result_page", record.get("reason"))
            self.assertEqual(out, Path(record["raw_path"]).parent, "artifacts stay in the out dir")

    def test_every_domain_denied_in_code_is_named_in_the_workflow(self) -> None:
        doc = WORKFLOW.read_text(encoding="utf-8")
        for host in fetch_text._SEARCH_HOSTS:
            domain = ".".join(host.split(".")[-2:])
            with self.subTest(domain=domain):
                self.assertIn(domain, doc, "the code denylist must not outrun the documented rule")


class ExtractionTests(unittest.TestCase):
    def test_gbk_page_decodes_and_strips_markup(self) -> None:
        raw = GBK_PAGE.encode("gb2312")
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            record = fetch_text.fetch_one(
                "https://www.nea.gov.cn/2025/page.html",
                out,
                scope="A",
                getter=body_response(raw, "text/html"),
            )
            self.assertTrue(record["ok"], record)
            self.assertEqual("gb2312", record["charset"])
            self.assertEqual("国家能源局：2025年全国电力工业统计数据", record["title"])
            text = Path(record["text_path"]).read_text(encoding="utf-8")
            self.assertIn("全国风电、光伏发电装机合计达14.1亿千瓦", text)
            self.assertIn('"12.0亿千瓦" & 风电6.4亿千瓦', text, "entities must be unescaped")
            self.assertNotIn("var t", text, "script bodies must not reach the evidence text")
            self.assertNotIn("color:#000", text, "style bodies must not reach the evidence text")

    def test_raw_bytes_are_kept_and_hashes_bind_both_artifacts(self) -> None:
        raw = GBK_PAGE.encode("gb2312")
        with TemporaryDirectory() as tmp:
            record = fetch_text.fetch_one(
                "https://www.nea.gov.cn/2025/page.html",
                Path(tmp),
                scope="A",
                getter=body_response(raw, "text/html"),
            )
            self.assertEqual(raw, Path(record["raw_path"]).read_bytes())
            import hashlib

            self.assertEqual(hashlib.sha256(raw).hexdigest(), record["raw_sha256"])
            text = Path(record["text_path"]).read_text(encoding="utf-8")
            self.assertEqual(
                hashlib.sha256(text.rstrip("\n").encode("utf-8")).hexdigest(),
                record["text_sha256"],
            )

    def test_json_bodies_pass_through_untouched(self) -> None:
        payload = b'{"records":[{"title":"policy","n":1}]}'
        with TemporaryDirectory() as tmp:
            record = fetch_text.fetch_one(
                "https://sousuo.www.gov.cn/search-gov/data?t=all&q=x",
                Path(tmp),
                scope="A",
                getter=body_response(payload, "application/json"),
            )
            self.assertTrue(record["ok"], record)
            self.assertEqual(payload.decode(), Path(record["text_path"]).read_text(encoding="utf-8").strip())

    def test_binary_content_types_are_refused_not_decoded(self) -> None:
        with TemporaryDirectory() as tmp:
            record = fetch_text.fetch_one(
                "https://example.org/image.png",
                Path(tmp),
                scope="A",
                getter=body_response(b"\x89PNG\r\n", "image/png"),
            )
            self.assertFalse(record["ok"])
            self.assertEqual("not_extractable", record["reason"])

    def test_a_remote_failure_does_not_hide_other_sources(self) -> None:
        import urllib.error

        def getter(url: str, _timeout: int):
            if "missing" in url:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return 200, {"content-type": "text/plain"}, b"evidence"

        with TemporaryDirectory() as tmp:
            report = fetch_text.fetch_many(
                ["https://example.org/missing", "https://example.org/ok"],
                Path(tmp),
                scope="B",
                getter=getter,
            )
            self.assertTrue(report["ok"])
            self.assertEqual(1, report["fetched"])
            self.assertEqual(1, report["failed"])
            reasons = [record.get("reason") for record in report["records"]]
            self.assertIn("http_error", reasons)

    def test_report_lands_in_the_output_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            report = fetch_text.fetch_many(
                ["https://example.org/ok"],
                out,
                scope="B",
                getter=body_response(b"hello", "text/plain"),
            )
            path = fetch_text.write_report(report, out)
            self.assertTrue(path.is_file())
            self.assertEqual(report["extractor"], json.loads(path.read_text(encoding="utf-8"))["extractor"])


class CliTests(unittest.TestCase):
    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TOOL), "fetch-text", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(ROOT),
        )

    def test_scope_is_required(self) -> None:
        with TemporaryDirectory() as tmp:
            result = self.run_tool("--url", "https://example.org/x", "--out-dir", tmp)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("--scope", result.stderr)

    def test_urls_file_accepts_comments_and_blanks(self) -> None:
        with TemporaryDirectory() as tmp:
            urls = Path(tmp) / "urls.txt"
            urls.write_text(
                "# locators for this claim\n\nhttps://cn.bing.com/search?q=x\n",
                encoding="utf-8",
            )
            result = self.run_tool("--urls-file", str(urls), "--out-dir", tmp, "--scope", "A")
            payload = json.loads(result.stdout[result.stdout.index("{") :])
            self.assertEqual(1, payload["refused"])
            self.assertEqual("search_result_page", payload["records"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
