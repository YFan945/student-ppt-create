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
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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

    def test_hosts_are_fetched_on_demand_and_only_classified(self) -> None:
        """Search and listing pages are classified, not topic-blocked (owner, 2026-09-29).

        A result page is not a *source* — that is an evidence rule for the pack.
        The production client still refuses non-public addresses; the getter here
        is the classification seam, not that client.
        """
        cases = {
            "https://cn.bing.com/search?q=x": "search_engine",
            "https://www.so.com/link?m=abc": "search_engine",
            "https://sousuo.www.gov.cn/search-gov/data?t=all&q=x": "listing",
            "https://www.nea.gov.cn/xwdt/gnxw.htm": "public",
            "https://www.gov.cn/zhengce/2021-10/26/content_5644989.htm": "public",
            "https://www.gov.cn/zhengce/news/P0202.pdf": "public",
            "https://www.nea.gov.cn/2025/page.html": "public",
        }
        with TemporaryDirectory() as tmp:
            for url, expected in cases.items():
                with self.subTest(url=url):
                    record = self.fetch(
                        url,
                        Path(tmp),
                        getter=body_response(b"<html><body>ok</body></html>", "text/html"),
                    )
                    self.assertTrue(record["ok"], record)
                    self.assertEqual(expected, record["host_class"])
                    if expected != "public":
                        self.assertIn("note", record)

    def test_non_public_literals_are_classified_private(self) -> None:
        for url in (
            "http://127.0.0.1:8080/docs",
            "http://10.0.0.5/status",
            "http://localhost/x",
            "http://169.254.1.1/x",
            "http://[::1]/x",
            "http://2130706433/",
            "http://[::ffff:127.0.0.1]/",
        ):
            with self.subTest(url=url):
                self.assertEqual("private", fetch_text.host_class(url))

    def test_private_literals_are_refused_before_connect(self) -> None:
        def open_once(*_args, **_kwargs):  # pragma: no cover - must never run
            raise AssertionError("a refused address must not be connected")

        urls = (
            "http://127.0.0.1:8080/docs",
            "http://10.0.0.5/status",
            "http://localhost/x",
            "http://169.254.1.1/link",
            "http://192.168.1.9/x",
            "http://240.0.0.1/x",
            "http://[::1]/x",
            "http://[fe80::1]/x",
            "http://[fc00::1]/x",
            "http://2130706433/secret",
            "http://[::ffff:127.0.0.1]/secret",
            "http://0.0.0.0/",
        )
        with patch.object(fetch_text, "_open_once", open_once), TemporaryDirectory() as tmp:
            for url in urls:
                with self.subTest(url=url):
                    record = fetch_text.fetch_one(url, Path(tmp), scope="A")
                    self.assertFalse(record["ok"])
                    self.assertEqual("address_not_allowed", record["reason"])
                    self.assertFalse(any(Path(tmp).glob("*.raw")))

    def test_a_redirect_to_a_private_address_is_refused_before_the_next_connect(self) -> None:
        class Opener:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def open(self, request, timeout=None):  # noqa: ANN001
                del timeout
                self.calls.append(request.full_url)
                if request.full_url.endswith("/start"):
                    raise fetch_text.RedirectRequestedError("http://127.0.0.1/secret")
                raise AssertionError(request.full_url)

        opener = Opener()

        def resolve(host: str, port: int):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        with self.assertRaises(fetch_text.AddressNotAllowedError) as caught:
            fetch_text.perform_fetch(
                "https://example.org/start",
                5,
                opener=opener,
                resolve=resolve,
            )
        self.assertEqual(["https://example.org/start"], opener.calls)
        self.assertEqual("http://127.0.0.1/secret", caught.exception.url)

    def test_a_name_that_resolves_to_a_private_address_is_refused(self) -> None:
        def resolve(_host: str, port: int):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]

        def open_once(*_args, **_kwargs):  # pragma: no cover - must never run
            raise AssertionError("must not connect")

        with (
            patch.object(fetch_text, "_resolve_host", resolve),
            patch.object(fetch_text, "_open_once", open_once),
            TemporaryDirectory() as tmp,
        ):
            record = fetch_text.fetch_one("https://intranet.example/doc", Path(tmp), scope="A")
        self.assertEqual("address_not_allowed", record["reason"])
        self.assertEqual("https://intranet.example/doc", record["final_url"])

    def test_an_oversized_body_is_refused_and_not_stored(self) -> None:
        class Response:
            status = 200
            headers = {"content-type": "text/plain"}

            def read(self, n: int = -1) -> bytes:
                return b"x" * (n if n and n > 0 else 64)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class Opener:
            def open(self, request, timeout=None):  # noqa: ANN001
                del request, timeout
                return Response()

        def resolve(_host: str, port: int):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        with self.assertRaises(fetch_text.BodyTooLargeError):
            fetch_text.perform_fetch(
                "https://example.org/huge",
                5,
                opener=Opener(),
                resolve=resolve,
                max_bytes=8,
            )
        real = fetch_text.perform_fetch

        def capped(url: str, timeout: int, **kwargs):
            kwargs.setdefault("max_bytes", 8)
            kwargs.setdefault("opener", Opener())
            kwargs.setdefault("resolve", resolve)
            return real(url, timeout, **kwargs)

        with patch.object(fetch_text, "perform_fetch", capped), TemporaryDirectory() as tmp:
            record = fetch_text.fetch_one("https://example.org/huge", Path(tmp), scope="A")
            self.assertEqual("body_too_large", record["reason"])
            self.assertFalse(any(Path(tmp).glob("*.raw")))

    def test_the_recorded_final_url_is_the_post_redirect_address(self) -> None:
        class Response:
            def __init__(self) -> None:
                self.status = 200
                self.headers = {"content-type": "text/plain"}
                self._body = b"evidence"

            def read(self, n: int = -1) -> bytes:
                if n is None or n < 0:
                    data, self._body = self._body, b""
                    return data
                data, self._body = self._body[:n], self._body[n:]
                return data

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class Opener:
            def open(self, request, timeout=None):  # noqa: ANN001
                del timeout
                if request.full_url.endswith("/start"):
                    raise fetch_text.RedirectRequestedError("https://example.org/landed")
                return Response()

        def resolve(_host: str, port: int):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

        real = fetch_text.perform_fetch

        def followed(url: str, timeout: int, **kwargs):
            kwargs.setdefault("opener", Opener())
            kwargs.setdefault("resolve", resolve)
            return real(url, timeout, **kwargs)

        with patch.object(fetch_text, "perform_fetch", followed), TemporaryDirectory() as tmp:
            record = fetch_text.fetch_one("https://example.org/start", Path(tmp), scope="A")
        self.assertTrue(record["ok"], record)
        self.assertEqual("https://example.org/landed", record["final_url"])

    def test_a_listing_url_is_still_requested_and_marked_listing(self) -> None:
        seen: list[str] = []

        def getter(url: str, timeout: int):
            seen.append(url)
            return body_response(b"<html><body>index</body></html>", "text/html")(url, timeout)

        with TemporaryDirectory() as tmp:
            record = self.fetch(
                "https://www.nea.gov.cn/xwfb/index.htm",
                Path(tmp),
                getter=getter,
            )
        self.assertEqual(["https://www.nea.gov.cn/xwfb/index.htm"], seen)
        self.assertTrue(record["ok"], record)
        self.assertEqual("listing", record["host_class"])

    def test_every_domain_classified_in_code_is_named_in_the_workflow(self) -> None:
        doc = WORKFLOW.read_text(encoding="utf-8")
        for host in fetch_text._SEARCH_HOSTS:
            domain = ".".join(host.split(".")[-2:])
            with self.subTest(domain=domain):
                self.assertIn(domain, doc, "the code classification must not outrun the documented rule")


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
            self.assertEqual(
                hashlib.sha256(Path(record["text_path"]).read_bytes()).hexdigest(),
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


SHELL = b'{"code":200,"msg":"\xe6\x93\x8d\xe4\xbd\x9c\xe6\x88\x90\xe5\x8a\x9f","data":null}'


class DegenerateChannelReportTests(unittest.TestCase):
    """The 2026-09-30 loop: ten identical 97-byte bodies, one model turn per variation.

    The verdict is computed by the tool and lands in the report it just wrote, so the
    executor reads a classification instead of inferring one from repeated files.
    """

    def shell_getter(self, url: str, _timeout: int):
        if "zhengcelibrary_bm" in url:
            return 200, {"content-type": "application/json"}, b'{"records":[{"title":"real"}]}'
        return 200, {"content-type": "application/json"}, SHELL

    def test_identical_bodies_across_distinct_requests_are_reported_once(self) -> None:
        urls = [
            f"https://sousuo.www.gov.cn/search-gov/data?t={t}&q=q{i}"
            for i, t in enumerate(("govall", "zhengcelibrary_gw", "zhengcelibrary_cp", "news"))
        ] + ["https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_bm&q=real"]
        with TemporaryDirectory() as tmp:
            report = fetch_text.fetch_many(urls, Path(tmp), scope="A", getter=self.shell_getter)
            self.assertEqual(1, len(report["degenerate_channels"]))
            verdict = report["degenerate_channels"][0]
            self.assertEqual("https://sousuo.www.gov.cn/search-gov/data", verdict["channel"])
            self.assertEqual("degenerate_echo", verdict["verdict"])
            self.assertEqual(4, verdict["distinct_requests"])
            flagged = [
                record["url"] for record in report["records"] if record.get("channel_verdict")
            ]
            self.assertEqual(4, len(flagged), flagged)
            self.assertNotIn(urls[-1], flagged, "a real answer on the same endpoint is not an echo")
            for record in report["records"]:
                if record["url"] in flagged:
                    self.assertIn("does not depend on the request", record["channel_note"])

    def test_a_clean_report_carries_an_empty_verdict_list(self) -> None:
        with TemporaryDirectory() as tmp:
            report = fetch_text.fetch_many(
                ["https://example.org/a", "https://example.org/b"],
                Path(tmp),
                scope="A",
                getter=lambda url, _t: (200, {"content-type": "text/plain"}, url.encode()),
            )
            self.assertEqual([], report["degenerate_channels"])
            self.assertFalse(any("channel_verdict" in record for record in report["records"]))

    def test_a_later_call_does_not_reopen_a_closed_channel(self) -> None:
        """The verdict has to survive the next invocation. The live run issued a fresh
        fetch-text per variation, and each one overwrote the report that held the echo.
        """
        first = [
            "https://sousuo.www.gov.cn/search-gov/data?t=govall&q=a",
            "https://sousuo.www.gov.cn/search-gov/data?t=news&q=b",
        ]
        later = "https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_bm&q=real"
        calls: list[str] = []

        def getter(url: str, _timeout: int):
            calls.append(url)
            return 200, {"content-type": "application/json"}, SHELL

        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            first_report = fetch_text.fetch_many(first, out, scope="A", getter=getter)
            fetch_text.write_report(first_report, out)
            second = fetch_text.fetch_many([later], out, scope="A", getter=getter)
            self.assertNotIn(later, calls, "a closed channel is not requested again")
            closed = [row for row in second["this_call"] if row.get("reason") == "channel_closed"]
            self.assertEqual([later], [row["url"] for row in closed])
            fetch_text.write_report(second, out)
            stored = json.loads((out / "fetch-text-report.json").read_text(encoding="utf-8"))
            self.assertNotIn("this_call", stored)
            urls = [row["url"] for row in stored["records"]]
            self.assertCountEqual([*first, later], urls)
            self.assertEqual(1, len(stored["degenerate_channels"]))

    def test_an_exact_url_is_reused_without_another_request(self) -> None:
        url = "https://www.gov.cn/zhengce/2021-10/26/content_5644989.htm"
        calls: list[str] = []

        def getter(target: str, _timeout: int):
            calls.append(target)
            return 200, {"content-type": "text/plain"}, "12亿千瓦".encode()

        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            fetch_text.write_report(
                fetch_text.fetch_many([url], out, scope="A", getter=getter), out
            )
            again = fetch_text.fetch_many([url], out, scope="A", getter=getter)
            self.assertEqual([url], calls)
            self.assertTrue(again["this_call"][0]["reused"])
            self.assertEqual(1, len(again["records"]))

    def test_a_nested_directory_folds_back_into_research_fetched(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp) / "research" / "fetched"
            url = "https://www.gov.cn/zhengce/2021-10/26/content_5644984.htm"
            report = fetch_text.fetch_many(
                [url],
                base / "u7",
                scope="A",
                getter=lambda _url, _t: (200, {"content-type": "text/plain"}, b"policy"),
            )
            path = fetch_text.write_report(report, base / "u7")
            self.assertEqual(base / "fetch-text-report.json", path)
            self.assertFalse((base / "u7" / "fetch-text-report.json").exists())
            self.assertTrue((base / "content-5644984-htm.txt").is_file() or any(base.glob("*.txt")))
            second = "https://www.nea.gov.cn/2025/stats.htm"
            fetch_text.write_report(
                fetch_text.fetch_many(
                    [second],
                    base / "u8",
                    scope="A",
                    getter=lambda _url, _t: (200, {"content-type": "text/plain"}, b"stats"),
                ),
                base / "u8",
            )
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([url, second], [row["url"] for row in stored["records"]])


class ArtifactCollisionTests(unittest.TestCase):
    """One accumulating out-dir is what makes a run auditable, and slugs collide.

    Every `sousuo.www.gov.cn/search-gov/data?…` request slugs to `data`; without
    disambiguation the second response overwrote the first while both records kept
    pointing at the surviving path — a record whose `raw_path` holds someone else's
    bytes, and the reason the executor started hand-rolling sub-directories (which then
    scattered the report the audit reads).
    """

    def test_a_colliding_slug_never_replaces_a_different_response(self) -> None:
        bodies = {
            "https://sousuo.www.gov.cn/search-gov/data?t=govall&q=a": b"first response",
            "https://sousuo.www.gov.cn/search-gov/data?t=news&q=b": b"second response",
        }
        with TemporaryDirectory() as tmp:
            report = fetch_text.fetch_many(
                list(bodies),
                Path(tmp),
                scope="A",
                getter=lambda url, _t: (200, {"content-type": "text/plain"}, bodies[url]),
            )
            paths = {record["url"]: record["raw_path"] for record in report["records"]}
            self.assertNotEqual(paths[list(bodies)[0]], paths[list(bodies)[1]])
            for url, body in bodies.items():
                self.assertEqual(body, Path(paths[url]).read_bytes(), url)

    def test_refetching_one_url_reuses_its_artifact(self) -> None:
        """Identical bytes are not a collision: re-fetching must stay idempotent."""
        url = "https://www.nea.gov.cn/2025/page.html"
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            first = fetch_text.fetch_one(
                url, out, scope="A", getter=body_response(b"same", "text/plain")
            )
            second = fetch_text.fetch_one(
                url, out, scope="A", getter=body_response(b"same", "text/plain")
            )
            self.assertEqual(first["raw_path"], second["raw_path"])
            self.assertEqual(b"same", Path(second["raw_path"]).read_bytes())

    def test_same_body_at_distinct_urls_keeps_separate_provenance(self) -> None:
        """They really did receive identical bytes, so one file binds both honestly."""
        urls = [
            f"https://sousuo.www.gov.cn/search-gov/data?t={t}" for t in ("govall", "news")
        ]
        with TemporaryDirectory() as tmp:
            report = fetch_text.fetch_many(
                urls,
                Path(tmp),
                scope="A",
                getter=lambda _url, _t: (200, {"content-type": "application/json"}, SHELL),
            )
            paths = {record["raw_path"] for record in report["records"]}
            self.assertEqual(2, len(paths))
            self.assertEqual(SHELL, Path(paths.pop()).read_bytes())


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
        # The refused URL keeps this offline: comment/blank parsing is what is under
        # test, not the network. A non-http scheme is refused before any request.
        with TemporaryDirectory() as tmp:
            urls = Path(tmp) / "urls.txt"
            urls.write_text(
                "# locators for this claim\n\nfile:///C:/tmp/not-http.txt\n",
                encoding="utf-8",
            )
            result = self.run_tool("--urls-file", str(urls), "--out-dir", tmp, "--scope", "A")
            payload = json.loads(result.stdout[result.stdout.index("{") :])
            self.assertEqual(1, payload["refused"])
            self.assertEqual("scheme_not_allowed", payload["records"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
