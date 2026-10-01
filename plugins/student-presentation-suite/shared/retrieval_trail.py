"""Retrieval response adapters and channel states, independent of the PPTX runtime.

Recognised envelopes provide locator candidates. Unknown prose cannot prove
backend execution; only structured runtime status may assert non-execution.
The hook pauses the affected search channel until main-session recovery or a
later recognised response. Evidence truth is checked against fetched documents.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Iterable, Mapping
from typing import Any

# One body received byte-identically by distinct requests is an echo of itself.
DEGENERATE_ECHO = "degenerate_echo"
# The retrieval never ran: the payload is the wrapper model's own writing about the
# query, occasionally including a tool call it composed as text instead of emitting.
SEARCH_BACKEND_NOT_EXECUTED = "backend_not_executed"
# The index ran and had nothing for that phrasing. The opposite of a dead backend.
INDEX_EMPTY = "index_empty"
RESULTS = "results"
UNKNOWN_PAYLOAD = "unknown_payload"
CHANNEL_RESET = "channel_reset"

DEGENERATE_ECHO_NOTE = (
    "this endpoint returned byte-identical content for distinct requests, so its answer does "
    "not depend on the request — leave the channel (another host, the publisher's document "
    "URL) instead of varying its parameters, and close the claim"
)

# Hosts (and redirect shapes) that only locate a document. One owner, shared with
# fetch_text.host_class and the WebFetch refusal. Kept in sync with research-workflow §七
# by tests/test_fetch_text.py.
SEARCH_LOCATOR_HOSTS = frozenset(
    {
        "bing.com",
        "www.bing.com",
        "cn.bing.com",
        "so.com",
        "www.so.com",
        "sogou.com",
        "www.sogou.com",
        "duckduckgo.com",
        "lite.duckduckgo.com",
        "html.duckduckgo.com",
        "search.brave.com",
        "brave.com",
        "mojeek.com",
        "www.mojeek.com",
        "search.yahoo.com",
        "yahoo.com",
        "baidu.com",
        "www.baidu.com",
        "google.com",
        "www.google.com",
    }
)
_LOCATOR_MARKERS = ("link?m=", "/link?", "/search?")


def endpoint_key(url: str) -> str:
    """The channel a request addresses: scheme + host + path, query and fragment dropped.

    Requests differing only in their query string are the same channel, which is the
    granularity a degenerate-answer verdict is useful at: the caller's next move is to
    leave the channel, and another `t=` / `page=` / `q=` on it is a variation of the
    thing that just failed rather than a second opinion.
    """
    parsed = urllib.parse.urlsplit(url)
    if not parsed.netloc:
        return ""
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def degenerate_channels(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Channels whose answer did not depend on the request.

    Mechanical and threshold-free: one byte-identical body received by two or more
    *distinct* request URLs means the endpoint ignored what it was asked for. Repeating
    one URL is deliberately not the signal — identical bytes are what a repeat is
    supposed to produce; varying the request and getting the same bytes is not.

    Reported per channel, never per request, so a downstream reader retires a channel
    instead of tallying the requests that hit it.
    """
    grouped: dict[tuple[str, str], set[str]] = {}
    for record in records:
        if not isinstance(record, Mapping) or not record.get("ok"):
            continue
        digest = str(record.get("raw_sha256") or "")
        url = str(record.get("url") or "")
        # Identical documents under tracking/signed URLs are normal. Retire only
        # identifiable locator/query endpoints, not arbitrary document paths.
        if not is_locator(url):
            continue
        if not digest or not url:
            continue
        channel = endpoint_key(url)
        if not channel:
            continue
        grouped.setdefault((channel, digest), set()).add(url)
    found: list[dict[str, Any]] = []
    for (channel, digest), urls in sorted(grouped.items()):
        if len(urls) < 2:
            continue
        found.append(
            {
                "channel": channel,
                "verdict": DEGENERATE_ECHO,
                "distinct_requests": len(urls),
                "raw_sha256": digest,
                "urls": sorted(urls),
            }
        )
    return found


def is_search_locator(url: str) -> bool:
    """True when the URL only locates a document: a search-engine host or a redirector."""
    parsed = urllib.parse.urlsplit(str(url or ""))
    host = (parsed.hostname or "").lower()
    if host in SEARCH_LOCATOR_HOSTS:
        return True
    lowered = str(url or "").lower()
    return any(marker in lowered for marker in _LOCATOR_MARKERS)


# Index and record-endpoint shapes. A policy document or a PDF is the thing to read,
# even when it sits near one of these paths.
_LISTING_PATH = re.compile(r"/(?:xwdt|xwfb|news|press-releases)/?$", re.IGNORECASE)
_INDEX_PAGE = re.compile(r"/index\.html?$", re.IGNORECASE)
_POLICY_DOCUMENT = re.compile(r"/zhengce/.*/content_[^/]+\.html?$", re.IGNORECASE)
_PDF_DOCUMENT = re.compile(r"\.pdf$", re.IGNORECASE)
_PUBLISHER_RECORD = ("sousuo.www.gov.cn", "/search-gov/data")


def is_listing_locator(url: str) -> bool:
    """True for a publisher index, news listing, or record endpoint — not the document.

    Policy pages (`/zhengce/.../content_*.htm`) and PDFs stay documents. Search-engine
    hosts are `is_search_locator`, not this.
    """
    parsed = urllib.parse.urlsplit(str(url or ""))
    path = parsed.path or ""
    if _PDF_DOCUMENT.search(path) or _POLICY_DOCUMENT.search(path):
        return False
    host = (parsed.hostname or "").lower()
    if host == _PUBLISHER_RECORD[0] and path.rstrip("/").endswith(_PUBLISHER_RECORD[1]):
        return True
    return _INDEX_PAGE.search(path) is not None or _LISTING_PATH.search(path) is not None


def is_locator(url: str) -> bool:
    """A URL that locates a document: search engine, redirector, or publisher listing."""
    return is_search_locator(url) or is_listing_locator(url)


def _has_backend_records(payload: str) -> bool:
    """Recognise locator candidates across structured and readable tool output.

    A recognised shape is a result candidate, not proof that the backend executed.
    Documents must still be fetched and the asserted facts bound to their text.
    """
    text = payload.strip()
    marker = "**web_search_prime_result_summary:**"
    if marker in text and text.startswith("Web search results for query:"):
        text = text.split(marker, 1)[1].strip()
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        # Search output is a locator: readable Markdown/plain links are useful
        # candidates too. Their claims and numbers still require document reads.
        return bool(re.search(r"https?://[^\s<>\"']+|\b10\.\d{4,9}/\S+", text))

    def contains_record(node: Any) -> bool:
        if isinstance(node, str) and node.lstrip().startswith(("{", "[")):
            try:
                return contains_record(json.loads(node))
            except ValueError:
                return False
        if isinstance(node, str):
            return bool(re.search(r"https?://[^\s<>\"']+|\b10\.\d{4,9}/\S+", node))
        if isinstance(node, list):
            return any(contains_record(item) for item in node)
        if not isinstance(node, dict):
            return False
        link = node.get("link") or node.get("url")
        if isinstance(link, str):
            parsed = urllib.parse.urlsplit(link)
            if parsed.scheme in {"http", "https"} and parsed.hostname:
                return True
        return any(contains_record(node.get(key)) for key in (
            "results", "links", "data", "result", "content", "text", "output"
        ))

    return contains_record(value)


def search_payload_signature(payload: str, *, execution_status: str = "") -> str:
    """Classify a supported locator envelope or explicit runtime non-execution.

    Unknown formats never establish outage. Empty responses stay unclassified.
    """
    # Only structured runtime metadata may assert non-execution. Prose, including
    # a model saying it has no search tool, cannot establish an environment fact.
    if execution_status == "not_executed":
        return SEARCH_BACKEND_NOT_EXECUTED
    text = str(payload or "")
    if not text.strip():
        return ""
    if _has_backend_records(text):
        return RESULTS
    try:
        envelope = json.loads(text)
    except ValueError:
        envelope = None
    if isinstance(envelope, dict) and any(envelope.get(k) == [] for k in ("results", "links", "data")):
        return INDEX_EMPTY
    if envelope == []:
        return INDEX_EMPTY
    lowered = text.lower()
    if re.fullmatch(r"(?:links:\s*)?(?:-\s*)?no links found\.?", lowered.strip()):
        return INDEX_EMPTY
    return UNKNOWN_PAYLOAD


def executions_from_payloads(entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Recompute search-log rows from stored payloads.

    The signature on the row is derived here, so a writer that omits or rewrites the
    field cannot hide a dead backend. Rows with an empty payload are dropped (fail-open).
    """
    rows: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("event") == CHANNEL_RESET:
            rows.append({"query": "", "status": "reset", "signature": CHANNEL_RESET})
            continue
        signature = search_payload_signature(
            str(entry.get("payload") or ""), execution_status=str(entry.get("execution_status") or "")
        )
        if not signature:
            continue
        rows.append(
            {
                "query": str(entry.get("query") or ""),
                "status": "ok" if signature == RESULTS else "failed",
                "signature": signature,
            }
        )
    return rows


def search_channel_closed(entries: Iterable[Mapping[str, Any]]) -> bool:
    """Fold state chronologically; a documented reset enables recovery."""
    closed = False
    for row in executions_from_payloads(entries):
        signature = row["signature"]
        if signature in {RESULTS, INDEX_EMPTY, CHANNEL_RESET}:
            closed = False
        elif signature == SEARCH_BACKEND_NOT_EXECUTED:
            closed = True
    return closed


def search_backend_never_executed(executions: Iterable[Mapping[str, Any]]) -> bool:
    """Did *every* failed search in this run fail because the backend never ran?

    Conservative by construction: it takes a run where each failed execution carries the
    `backend_not_executed` signature, so a run with any genuinely empty-but-executed
    failure is not mislabelled, and a log that records no signature at all (older
    writers) can never trigger it. What it buys is the one thing the bare
    `search_unavailable` cannot say: "this session's search layer was down", which is
    an environment fact the operator can fix, not evidence about the subject.
    """
    failed = [entry for entry in executions if str(entry.get("status") or "") == "failed"]
    if not failed:
        return False
    # A payload that carries backend records means the backend ran in this session.
    # Role-played failures beside one real record are not "the search layer was down".
    if any(str(entry.get("signature") or "") == RESULTS for entry in executions):
        return False
    return all(
        str(entry.get("signature") or "") == SEARCH_BACKEND_NOT_EXECUTED for entry in failed
    )
